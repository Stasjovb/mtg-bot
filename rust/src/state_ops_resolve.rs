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
//! - **ETB-triggered effects** (round-9 slice; Slice 3 of the
//!   ETB-trigger closure retired the inline path). After
//!   post-resolve movement places a permanent on the controller's
//!   battlefield, every ENTERS-shaped triggered ability on the
//!   source printing fires through the predicate-path
//!   `dispatch_event(Event::Enters, source_id)` walker. Legacy
//!   `etb_effects: Vec<Effect>` entries are bridged to the same
//!   substrate at parse time (`cards.rs::parse_printing` synthesizes
//!   a `TriggeredAbility { event: Enters, predicate: SourceIsSelf,
//!   effect: ... }` per `etb_effects` entry), so a printing carrying
//!   `etb_effects=[DrawCards(1)]` and a printing carrying
//!   `triggered_abilities=[{event: enters, predicate: source_is_self,
//!   effect: draw_cards(1)}]` produce identical observable state.
//!   First-slice simplifications (mirrored in
//!   `tests_rust/test_resolve.py`):
//!   - **Real on-stack triggering** post-Slice-3. ENTERS triggers
//!     get pushed onto the stack via `push_triggered_ability` and
//!     resolve LIFO on the next priority round. Pre-Slice-3 they
//!     applied inline at resolution time; the on-stack shape is
//!     CR-faithful and supports response windows.
//!   - **Gating: only fire when the source landed on battlefield.**
//!     If post-resolve sent the source to graveyard (instant /
//!     sorcery) or left it in place (empty card_types escape
//!     hatch), ENTERS triggers are skipped — by definition the
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

use crate::bf_iter::bf_iter_etb_sorted;
use crate::cards::{parse_printing, Effect, Event, RegistryData, TargetFilter};
use crate::state::{
    GameObject, GameState, PendingDecision, StackItem, StackItemKind, UeotModifier,
};
use crate::state_ops_decisions::auto_resolve_pending;
use crate::state_ops_zones::{
    mark_left_battlefield_if_nonland, ZONE_BATTLEFIELD, ZONE_EXILE,
    ZONE_GRAVEYARD, ZONE_HAND, ZONE_LIBRARY,
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
    // CE4 closure: when this resolution lands the source on the
    // battlefield (ResolveCreature / ResolveArtifact / Enchantment /
    // Planeswalker — every permanent-typed source), stamp a fresh
    // ETB timestamp so it sorts after every previously-ETBed object.
    // Non-bf destinations (graveyard for instants / sorceries) leave
    // the field at its prior (likely zero) value — the snapshot /
    // fingerprint only sort-reads `etb_timestamp` for bf entries.
    if dest_zone == ZONE_BATTLEFIELD {
        obj.etb_timestamp = crate::state::reserve_etb_timestamp(state);
        // CE20 Slice 5 (Walker loyalty — `starting_loyalty` ETB
        // seeding). CR 606.5b: a planeswalker enters with loyalty
        // counters equal to its printed starting loyalty. No-op for
        // non-walker printings.
        crate::state::seed_starting_loyalty_for_etb(state, &mut obj);
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
// --- ETB-trigger substrate (Slice 1) -----------------------------
//
// Implements the dispatch walker + push helper that fan
// `Event::Enters` (and future events) out to every triggered
// ability on every printing on the battlefield. Mirrors Python's
// `dispatch_event` (`src/mtg_bot/actions.py:3283-3399`) +
// `push_triggered_ability` (`src/mtg_bot/actions.py:3172-3280`).
//
// Slice 1 scope (per `docs/RUST_ETB_TRIGGER_AUDIT.md` §6.1):
//
// 1. Walk `bf_iter_etb_sorted(state)` (CE5-introduced helper at
//    `rust/src/bf_iter.rs:61`) — order matches Python's
//    `list(state.battlefield)`.
// 2. Snapshot the bf list AT DISPATCH ENTRY so triggers that ETB
//    new permanents during dispatch don't observe their own event
//    in the same pass (mirrors Python's
//    `actions.py:3343-3345` snapshot comment).
// 3. For each (source, ability) pair, check (a) the event matches
//    and (b) the predicate evaluates true.
// 4. Once-per-turn gate: skip if `(source_id, ability_index) in
//    state.triggered_this_turn`.
// 5. On match + non-gated: call `push_triggered_ability` to put a
//    `StackItem::new_trigger` on the stack.
//
// **Defers to Slice 2+:**
// - APNAP ordering (Python deliberately doesn't either — see
//   audit §2.5).
// - Panharmonicon-shape `etb_trigger_multiplier`.
// - Target selection on triggers that need it (DealDamage trigger
//   with a chosen target). Slice 1 only proves DrawCards-shape /
//   GainLife-shape (no target) for the substrate smoke probe.
// - Fan-out from the other 11 ETB-stamping sites (audit §4).
// - Combat-damage aggregator dedup.

/// **Slice 1 — dispatch a single event to every triggered ability
/// on the battlefield.** Walks every permanent in
/// ETB-timestamp order, matches each printing's
/// `triggered_abilities` against `(event, subject_id, source)`,
/// and pushes matching triggers onto the stack via
/// `push_triggered_ability`.
///
/// Slice 1 surface accepts `Event::Enters`. Slice 5 adds
/// `Event::Dies`. Other variants raise `PyValueError` loudly so the
/// parser surface and the dispatcher's coverage stay consistent.
///
/// Slice 5 (DIES): the dying object has already been moved to the
/// graveyard by the caller. The walker still snapshots the
/// **battlefield** as the observer-set, but DIES dispatch
/// additionally includes the dying object as an "extra observer" so
/// `Predicate::SourceIsSelf` triggers (the canonical "when this
/// creature dies" shape) can match. Mirrors Python's
/// `dispatch_event(..., extra_observers=[obj])` pattern at
/// `src/mtg_bot/turn.py:281` for the `move_off_battlefield` site.
pub(crate) fn dispatch_event(
    state: &mut GameState,
    event: Event,
    subject_id: u32,
) -> PyResult<()> {
    // Defensive: Slice 9 wires ENTERS + DIES + CAST + ATTACKS +
    // BLOCKS + LEAVES_BATTLEFIELD; round-58 adds BECOMES_TAPPED.
    // Other events declared in the enum stay raise-on-dispatch so a
    // future caller who skipped the fan-out plan surfaces it loudly
    // rather than silently no-op.
    if event != Event::Enters
        && event != Event::Dies
        && event != Event::Cast
        && event != Event::Attacks
        && event != Event::Blocks
        && event != Event::LeavesBattlefield
        && event != Event::BecomesTapped
    {
        return Err(PyValueError::new_err(format!(
            "dispatch_event: event {event:?} is not yet wired in Slice 9; \
             only Event::Enters, Event::Dies, Event::Cast, Event::Attacks, \
             Event::Blocks, Event::LeavesBattlefield, and \
             Event::BecomesTapped dispatch today"
        )));
    }

    // Snapshot the bf source-id + ability-payload list AT ENTRY so
    // triggers that ETB new permanents during dispatch don't
    // observe their own event in the same pass. Materializes
    // (source_id, source_controller, ability_index, effect-clone)
    // tuples — once the bf-snapshot is done we no longer hold an
    // immutable borrow on `state`, so `push_triggered_ability`
    // (which mutates `state.stack`) is free to fire.
    //
    // For DIES events, the dying object has been moved to the
    // graveyard already; we synthesize an EXTRA observer entry for
    // it (mirroring Python's `extra_observers=[obj]`) so an
    // `IsSelf`-shape "when this creature dies" trigger can still
    // see itself as a candidate observer.
    //
    // For CAST events, the spell-being-cast is still in the hand
    // zone at dispatch time (Rust's no-stack `cast_creature`
    // dispatches CAST after mana payment but BEFORE the move-to-bf).
    // The subject is the object in the hand; SourceIsSelf-shape
    // "when you cast this" triggers need the casting card as an
    // extra observer so the predicate's source==subject test can
    // match. Mirrors the DIES extra-observer pattern.
    let firings: Vec<(u32, u8, u32, Effect, bool)> = {
        let bf = bf_iter_etb_sorted(state);
        // Build the observer list: every bf permanent, plus
        // event-specific extra observers (the dying creature for
        // DIES, the cast-spell for CAST). The extra observer is
        // keyed by id so the ability-walk lookup uses the same
        // registry lookup the bf permanents go through.
        let mut observer_entries: Vec<(u32, u8, u32)> = bf
            .iter()
            .map(|o| (o.id, o.controller, o.printing_id))
            .collect();
        if event == Event::Dies
            || event == Event::Cast
            || event == Event::LeavesBattlefield
        {
            // DIES: look up the dying object (now in graveyard).
            // CAST: look up the cast object (still in hand).
            // LEAVES_BATTLEFIELD: look up the leaving object (now
            // in graveyard / exile / hand / library depending on
            // the bf-exit primitive that fired the dispatch). The
            // four-zone walk + library covers each destination.
            //
            // All three share the multi-zone walk shape. Skip if
            // not found — the dispatch caller is loud-but-safe.
            //
            // Dedup guard: if the subject somehow also appears in
            // `bf` (shouldn't happen for these events' callers),
            // don't double-register it as an observer.
            if !observer_entries.iter().any(|(id, _, _)| *id == subject_id) {
                'outer: for player in &state.players {
                    for zone in [
                        &player.hand,
                        &player.library,
                        &player.battlefield,
                        &player.graveyard,
                        &player.exile,
                    ] {
                        for obj in zone.iter() {
                            if obj.id == subject_id {
                                observer_entries.push((
                                    obj.id,
                                    obj.controller,
                                    obj.printing_id,
                                ));
                                break 'outer;
                            }
                        }
                    }
                }
            }
        }
        let mut firings = Vec::new();
        for (source_id, source_controller, printing_id) in &observer_entries {
            // Resolve the source's printing -> its triggered_abilities.
            let printing = match state.registry.lookup(*printing_id) {
                Some(p) => p,
                None => continue,
            };
            for (ability_index, ability) in
                printing.triggered_abilities.iter().enumerate()
            {
                if ability.event != event {
                    continue;
                }
                if !ability
                    .predicate
                    .matches(state, *source_id, subject_id)
                {
                    continue;
                }
                // Once-per-turn gate: skip if already fired this turn.
                if ability.once_per_turn
                    && state
                        .triggered_this_turn
                        .contains(&(*source_id, ability_index as u32))
                {
                    continue;
                }
                firings.push((
                    *source_id,
                    *source_controller,
                    ability_index as u32,
                    ability.effect.clone(),
                    ability.once_per_turn,
                ));
            }
        }
        firings
    };

    // Push each matching firing onto the stack. Order matches the
    // bf walk (Python's "no APNAP simplification" — audit §2.5).
    for (source_id, controller, ability_index, effect, once_per_turn) in firings {
        push_triggered_ability(
            state,
            source_id,
            controller,
            ability_index,
            effect,
            once_per_turn,
        )?;
    }
    Ok(())
}

/// **Round-58 BECOMES_TAPPED event bridge — the centralized "tap a
/// permanent and fire its becomes-tapped triggers" chokepoint.**
///
/// This is the Rust analogue of Python's `turn.tap_permanent`
/// (`src/mtg_bot/turn.py:542-571`): flip `tapped` on the battlefield
/// permanent `obj_id`, and — iff the flip actually changed state
/// (the object was UNTAPPED and is now tapped) — dispatch
/// `Event::BecomesTapped` for it.
///
/// **No-op-if-already-tapped parity.** Python's `tap_permanent`
/// early-returns when `obj.tapped` is already True (no re-trigger).
/// This helper mirrors that exactly: a tap of an already-tapped
/// permanent is a silent no-op (no event, no `Arc::make_mut` clone).
/// The "did it actually change" gate is what makes the event-firing
/// set byte-equal to Python's.
///
/// **Subject stays on the bf.** Tapping does not move the permanent,
/// so the subject is still on the battlefield at dispatch time —
/// `dispatch_event`'s bf-snapshot observer set already contains it
/// and `Predicate::SourceIsSelf` ("whenever this creature becomes
/// tapped") matches naturally via `source_id == subject_id`. No
/// DIES/CAST-style extra-observer entry is needed (this is exactly
/// the ATTACKS shape — see the `Event::Attacks` dispatch at
/// `state_ops_combat.rs`).
///
/// **Why a free function, not a `tap_object` rewrite.** The existing
/// `tap_object` pymethod in `state_ops_tap.rs` is a test/cost
/// primitive that deliberately does NOT dispatch (its callers
/// pre-date the event). Routing it through dispatch would change
/// every existing tap-cost test's stack invariants. Per the
/// per-file isolation rule, the production tap sites
/// (`state_ops_mana`, `state_ops_actions`, the TapTarget-family
/// effect arms in this file, and the attack-tap in
/// `state_ops_combat`) each inline a flip + a call to this single
/// helper so the dispatch logic lives in exactly one place and the
/// no-op gate can't drift between sites.
///
/// Returns `Ok(true)` if the permanent became tapped (event fired),
/// `Ok(false)` if it was already tapped / not on any bf (no-op), or
/// `Err` if the dispatched trigger's effect raised.
pub(crate) fn tap_permanent_and_dispatch(
    state: &mut GameState,
    obj_id: u32,
) -> PyResult<bool> {
    // Phase 1: flip, scoped so the Arc::make_mut borrow is released
    // before dispatch_event re-borrows state mutably. Mirrors the
    // `state_ops_tap::tap_object` CoW shape: skip the make_mut clone
    // entirely on the already-tapped no-op path.
    let mut changed = false;
    'find: for player in state.players.iter_mut() {
        if player.battlefield.iter().any(|o| o.id == obj_id) {
            // Pre-check tapped before paying the make_mut clone.
            let already_tapped = player
                .battlefield
                .iter()
                .find(|o| o.id == obj_id)
                .map(|o| o.tapped)
                .unwrap_or(true);
            if already_tapped {
                break 'find;
            }
            let zone: &mut Vec<GameObject> =
                std::sync::Arc::make_mut(&mut player.battlefield);
            for obj in zone.iter_mut() {
                if obj.id == obj_id {
                    obj.tapped = true;
                    changed = true;
                    break 'find;
                }
            }
        }
    }
    if !changed {
        // Already tapped, or no bf permanent with that id — Python's
        // `tap_permanent` early-return path. No event.
        return Ok(false);
    }
    // Phase 2: fire becomes-tapped triggers. Same dispatcher every
    // other event flows through.
    dispatch_event(state, Event::BecomesTapped, obj_id)?;
    Ok(true)
}

/// **Slice 1 — push one triggered ability onto the stack.** Adds a
/// `StackItem::new_trigger` carrying the source object's id, the
/// trigger's controller, and the payload effect. Bumps the
/// once-per-turn ledger when the ability is gated.
///
/// Slice 1 simplifications (deferred to later slices):
/// - **No target selection.** Effects that need a target
///   (DealDamage with AnyPlayer / AnyCreature) fall back on the
///   existing `apply_effect` resolution-time targeting (defending
///   player / first defender bf object). Real MTG picks targets at
///   push time; deferred to Slice 4+ along with the rest of the
///   target-on-cast plumbing.
/// - **No fizzle check.** Targets are picked at resolve time, so
///   "no legal targets at push" is moot under Slice 1's deferred-
///   targeting shape. Slice 4+ adds the fizzle gate.
/// **Tier-C target-seating shared sub-substrate.** The deterministic
/// no-agent push-time target seat for a SAFE *targeted* triggered
/// ability — the single byte-equal-able first-legal rule shared by
/// every per-card lever-a consumer (Sunset Saboteur today; Exosuit
/// Savior next), mirrored exactly by the Python seat at
/// `actions.py:_put_triggered_ability_on_stack` (the
/// `controller.agent is None` branch).
///
/// **The rule (identical on both engines, by construction).** Scan
/// `state.players` in ascending seat index; within each player's
/// `battlefield` Vec in insertion order; return the id of the first
/// object that passes the effect's slot filter. This is exactly
/// Python's `Effect._enumerate_for_filter` order
/// (`base.py` — battlefield in list order then players in order);
/// `legal_targets[0]` IS this pick, which is what the campaign's
/// `_PickFirstLegalTargetAgent` shim family encodes. The
/// cross-engine harness keeps object ids + bf insertion order in
/// lockstep (`build_rust_state` registers in Python bf order), so
/// "smallest bf index passing the filter" names the SAME object on
/// both engines.
///
/// **Gated to lever-a effects ONLY.** Returns `None` for every
/// effect that is NOT a Tier-C target-seating lever variant —
/// including every one of the 20+ live UNTARGETED safe triggers
/// (`DrawCards` / `GainLife` / `Surveil` / `CreateToken` / …). For
/// those `push_triggered_ability` takes the unchanged
/// `new_trigger` path → byte-identical behavior, zero regression.
/// The per-card filter is the lever variant's own (matched here):
/// `PutPlusOneCounterOnOpponentsCreature` → first creature an
/// opponent of `controller` controls. (`new_trigger_with_target`
/// is the EXISTING constructor — CE20 Slice 4 / Equipment-equip;
/// no new `StackItem`/`TriggerPayload` field, see `state.rs`.)
///
/// **None semantics at the call site.** `count_min>=1` + no eligible
/// target ⇒ the trigger must NOT be pushed (Python fizzles,
/// `return False` — CR 603.3c). `count_min==0` + no eligible ⇒ push
/// with no target (the optional effect resolves as a no-op,
/// byte-equal with Python's `targets=()`). The call site encodes
/// this; the helper only answers "which object, if any".
fn first_legal_trigger_target(
    state: &GameState,
    source_id: u32,
    controller: u8,
    effect: &Effect,
) -> Option<u32> {
    match effect {
        // Sunset Saboteur (`ATTACKS`, source_is_self,
        // `PutPlusOneCounterOnOpponentsCreature`): slot filter
        // `IsCreature() & ControlledByOpponent()`. Opponent = any
        // player whose seat != the source-controller's seat (2-seat
        // model). Scan ascending seat then bf-Vec order; first
        // creature an opponent controls.
        Effect::PutPlusOneCounterOnOpponentsCreature { .. } => {
            for (pidx, player) in state.players.iter().enumerate() {
                if pidx as u8 == controller {
                    continue; // own creatures excluded by the filter
                }
                for obj in player.battlefield.iter() {
                    let printing =
                        state.registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        return Some(obj.id);
                    }
                }
            }
            None
        }
        // Exosuit Savior (`ENTERS`, source_is_self,
        // `ReturnTargetPermanentYouControlToOwnersHand`): slot filter
        // `ControlledByYou() & ~IsPlayer() & ~IsSource()`. Scan the
        // source-controller's OWN battlefield in Vec order; first
        // permanent that is not the source (players are never bf
        // objects, so `~IsPlayer()` is satisfied by construction).
        // `count_min=0` (optional) — `None` here means "no eligible
        // own permanent": `push_triggered_ability` then pushes via
        // the unchanged `new_trigger` path and the resolve arm
        // no-ops (byte-equal with Python's `targets=()` decline). It
        // is NOT in `lever_trigger_requires_target` so the trigger is
        // NEVER fizzle-skipped (contrast Sunset Saboteur).
        Effect::ReturnTargetPermanentYouControlToOwnersHand => {
            let cidx = controller as usize;
            for obj in state.players[cidx].battlefield.iter() {
                if obj.id == source_id {
                    continue; // ~IsSource()
                }
                return Some(obj.id);
            }
            None
        }
        // Every other effect (all existing untargeted safe triggers,
        // and any non-lever targeted trigger the engine handles
        // elsewhere): NOT a target-seating consumer — the helper is
        // a no-op so `push_triggered_ability` takes the unchanged
        // `new_trigger` path.
        _ => None,
    }
}

/// True iff `effect` is a Tier-C target-seating lever-a variant whose
/// trigger MUST fizzle (NOT be pushed) when no legal target exists —
/// the `count_min>=1` cards. Sunset Saboteur's
/// `PutPlusOneCounterOnOpponentsCreature` is `count_min=1` (CR
/// 603.3c: a targeted ability with no legal target is removed from
/// the stack — Python's `_put_triggered_ability_on_stack` logs
/// "no legal targets; fizzles" and `return False`). The
/// `count_min==0` optional cards — Exosuit Savior's
/// `ReturnTargetPermanentYouControlToOwnersHand` — are
/// DELIBERATELY NOT in this set: with no eligible target they push
/// via the unchanged `new_trigger` path and the resolve arm no-ops
/// (byte-equal with Python's `targets=()` `Bounce.resolve`
/// early-return — the optional was simply declined, not fizzled).
fn lever_trigger_requires_target(effect: &Effect) -> bool {
    matches!(effect, Effect::PutPlusOneCounterOnOpponentsCreature { .. })
}

pub(crate) fn push_triggered_ability(
    state: &mut GameState,
    source_id: u32,
    controller: u8,
    ability_index: u32,
    effect: Effect,
    once_per_turn: bool,
) -> PyResult<()> {
    // Tier-C target-seating: compute the deterministic first-legal
    // seat. `None` for every non-lever effect (every existing safe
    // trigger — preserves the byte-identical pre-substrate path).
    let tgt = first_legal_trigger_target(state, source_id, controller, &effect);
    if tgt.is_none() && lever_trigger_requires_target(&effect) {
        // `count_min>=1` + no eligible target: the trigger fizzles
        // and is NEVER pushed (CR 603.3c), byte-equal with Python's
        // `_put_triggered_ability_on_stack` "no legal targets;
        // fizzles" `return False`. The once-per-turn ledger is NOT
        // bumped (the ability didn't go on the stack — matches
        // Python, where `should_fire_trigger` already passed but the
        // fizzle path returns before the StackItem append; the ledger
        // bump is downstream of the push in both engines).
        return Ok(());
    }
    match tgt {
        Some(t) => state.stack.push(StackItem::new_trigger_with_target(
            source_id,
            controller,
            effect,
            ability_index,
            t,
        )),
        // Unchanged path: untargeted safe triggers AND the
        // `count_min==0` optional lever cards with no eligible target
        // (push with no seat → the optional effect resolves as a
        // no-op, byte-equal with Python's `targets=()`).
        None => state
            .stack
            .push(StackItem::new_trigger(source_id, controller, effect, ability_index)),
    }
    if once_per_turn {
        state
            .triggered_this_turn
            .insert((source_id, ability_index));
    }
    Ok(())
}

pub(crate) fn apply_effect_pub(
    state: &mut GameState,
    effect: &Effect,
    source_obj_id: u32,
) -> PyResult<()> {
    apply_effect(state, effect, source_obj_id)
}

/// **Controller-aware variant of `apply_effect_pub`.** Swaps
/// `state.current_resolve_source_controller` to `Some(controller)`
/// for the duration of the inner `apply_effect` call, restoring the
/// prior value (typically `None`) afterward.
///
/// Effect arms that need the source's controller (today
/// `Effect::DrawCards` per I59, `Effect::GainLife` per I60,
/// `Effect::DamageEachOpponent` per I63, and `Effect::DealDamage`
/// per I64 — see CR 119.5 / the "Controller of effect" convention
/// notes in those arms' comments) read the swapped field. Arms that
/// don't care continue to read `state.active_player` unchanged —
/// back-compat for every existing call site that hasn't been
/// migrated.
///
/// **Why this exists.** The pre-fix DrawCards arm read
/// `state.active_player` as the controller, which is wrong when the
/// resolving spell / triggered ability has a controller != the
/// active player (e.g. an opponent's instant resolves during your
/// turn and draws cards — pre-fix the spell would have drawn cards
/// for YOU, not its actual controller). Mirrors Python's
/// `DrawCards.resolve(state, controller_id, targets)` which takes
/// the source's controller explicitly.
///
/// **Pattern mirrored:** the CE20 Slice 1 bridge's `active_player`
/// swap (`state_ops_actions.rs`) and Slice 4's
/// `current_resolve_payload_target_id` swap. Cleaner than mutating
/// `active_player` because it doesn't touch any of the OTHER
/// `active_player`-keyed arms (PumpCreaturesYouControl, search-zone
/// resolvers, etc.) — those still mean exactly what they meant
/// before. Only arms that explicitly opt into reading
/// `current_resolve_source_controller` change behavior.
///
/// **Callers (post-I61):** every pending-decision dispatcher in
/// `state_ops_decisions.rs` (MayDo / IfYouDo / ChooseMode /
/// OptionalManaCost auto-resolve + submit). The in-tree stack
/// resolver branches still set the slot manually around their
/// `apply_effect` loops (avoids an extra function-call layer for the
/// hot stack-resolve path); the helper is the cleaner route for the
/// one-shot pending-decision path where readability beats nano-perf.
pub(crate) fn apply_effect_pub_with_controller(
    state: &mut GameState,
    effect: &Effect,
    source_obj_id: u32,
    controller: u8,
) -> PyResult<()> {
    let saved = state.current_resolve_source_controller;
    state.current_resolve_source_controller = Some(controller);
    let result = apply_effect(state, effect, source_obj_id);
    state.current_resolve_source_controller = saved;
    result
}

/// **Slice 2 — drain the deferred ETB dispatch queue.** Effect arms
/// that move permanents onto the battlefield (RS2-RS12 in
/// `docs/RUST_ETB_TRIGGER_AUDIT.md`) push the entered permanent's id
/// onto `state.pending_etb_dispatches` instead of dispatching directly.
/// The surrounding caller (every site that owns a "resolving slot" on
/// the stack — `resolve_top_of_stack`, `_pause`, plus the standalone
/// bf-entry primitives `play_land` / `cast_creature` / `move_object` /
/// `move_object_from_graveyard_to_battlefield` /
/// `register_and_inject_object` / `return_paired_exiles_for` /
/// `resolve_manifest_dread_to_battlefield`) calls this drainer AFTER
/// the resolving slot is removed from the stack so the trigger pushes
/// land on top of a clean (or at least non-resolving) stack.
///
/// **Drain order:** FIFO. The arm pushes ids in the order they
/// landed on the battlefield; the drainer dispatches in the same
/// order, mirroring Python's per-permanent
/// `put_into_battlefield -> _trigger_etb_abilities` loop.
///
/// **Re-entrancy:** drain takes the queue with `std::mem::take` to
/// avoid borrow conflicts; if a dispatch's effect re-fills the queue
/// (e.g. a chain of ETB triggers that themselves create permanents),
/// the new ids land in the queue and a subsequent drain picks them
/// up. Today the only way to re-fill mid-drain is via a triggered
/// ability that creates a token / reanimates — substrate-wise that's
/// supported and the drain loops until empty.
pub(crate) fn drain_pending_etb_dispatches(state: &mut GameState) -> PyResult<()> {
    // Loop until the queue stays empty across a drain (re-entrant
    // dispatches can re-fill mid-loop). Bounded by the number of
    // permanents that can enter in a single resolution — finite,
    // not unbounded.
    loop {
        let drained: Vec<u32> = std::mem::take(&mut state.pending_etb_dispatches);
        if drained.is_empty() {
            return Ok(());
        }
        for entered_id in drained {
            dispatch_event(state, Event::Enters, entered_id)?;
        }
    }
}

/// **Slice 5 — DIES sibling of `drain_pending_etb_dispatches`.**
/// Mirror-shape drainer for `state.pending_dies_dispatches`. Called
/// by `apply_sbas` after the SBA destroy loop completes; iterates
/// the queued ids in FIFO order, dispatching `Event::Dies` for each.
/// Re-entrant fills (a DIES trigger that pushes a permanent onto bf
/// — Reaper-King-shape — re-enters into the ENTERS queue; a DIES
/// trigger that schedules ANOTHER death is rarer but the loop
/// handles it cleanly).
pub(crate) fn drain_pending_dies_dispatches(state: &mut GameState) -> PyResult<()> {
    loop {
        let drained: Vec<u32> = std::mem::take(&mut state.pending_dies_dispatches);
        if drained.is_empty() {
            return Ok(());
        }
        for dead_id in drained {
            dispatch_event(state, Event::Dies, dead_id)?;
        }
    }
}

/// **Slice 8 — LEAVES_BATTLEFIELD sibling of
/// `drain_pending_etb_dispatches` / `drain_pending_dies_dispatches`.**
/// Drains `state.pending_leaves_dispatches` in FIFO order,
/// dispatching `Event::LeavesBattlefield` for each queued id.
/// Called by every bf-exit primitive AFTER the primitive's mutation
/// completes (and AFTER any sibling DIES drain, so death-then-leaves
/// stack-push order matches Python's
/// `move_off_battlefield` sequence at `turn.py:280-289`).
///
/// Re-entrant fills: a LEAVES trigger whose resolution causes
/// another bf-exit (e.g. exile-on-LTB) re-enters into the queue;
/// the outer loop drains FIFO until the queue is empty.
pub(crate) fn drain_pending_leaves_dispatches(state: &mut GameState) -> PyResult<()> {
    loop {
        let drained: Vec<u32> = std::mem::take(&mut state.pending_leaves_dispatches);
        if drained.is_empty() {
            break;
        }
        for leaving_id in drained {
            dispatch_event(state, Event::LeavesBattlefield, leaving_id)?;
        }
    }
    // Round-55 token-cease-to-exist (CR 111.7 / 704.5d). The LEAVES
    // (and any preceding DIES) dispatch has now fired with the token
    // still in its destination zone (so its own death/leave triggers
    // saw it as an extra observer — Python's by-reference semantics
    // in `move_off_battlefield`). Now remove it so the final state
    // has the token in NO zone, byte-equal to Python (whose token
    // never lands in graveyard/exile/hand at all). A LEAVES trigger
    // that itself caused a token bf-exit re-filled the queue during
    // the loop above; this single drain after the loop catches it
    // (the drain is itself idempotent / re-entrant-safe).
    crate::state_ops_zones::drain_pending_token_cease(state);
    Ok(())
}

/// Read effective power of a battlefield creature (printed +
/// UEOT power-bonus modifiers, sized off the SetBasePT / become-
/// land-creature overrides per CR 613.4 layer 7b/7c). Returns 0
/// for non-creatures or unknown ids.
///
/// Inlines `state_ops_combat::battlefield_creature_power` because
/// that helper is module-private to the combat slice (per the
/// per-slice file-isolation rule). Matches its semantics exactly:
/// SetBasePT > BecomeLandCreature > printed_base, plus
/// UEOT power_bonus addends. Used by the FightTargetCreatureWith
/// TargetCreature resolve arm to size each side's contribution to
/// the simultaneous-damage exchange.
///
/// **Inlining note (cross-file friction).** Same shape as the
/// `draw_card` and `dispatch_event` inlinings already in this
/// file — the per-slice rule forbids touching `state_ops_combat`
/// from this slice. A follow-up consolidation slice can collapse
/// these once that constraint relaxes; the public
/// `state.effective_power(obj_id)` PyMethod returns the same
/// value but is a `&self` getter not callable from `apply_effect`'s
/// `&mut state` borrow path without splitting the borrow.
fn read_battlefield_creature_power(state: &GameState, obj_id: u32) -> i16 {
    // Locate the object on either player's bf.
    let mut found: Option<(usize, &GameObject)> = None;
    for (idx, player) in state.players.iter().enumerate() {
        if let Some(obj) = player.battlefield.iter().find(|o| o.id == obj_id) {
            found = Some((idx, obj));
            break;
        }
    }
    let Some((player_idx, obj)) = found else {
        return 0;
    };
    let Some(printing) = state.registry.printings.get(obj.printing_id as usize) else {
        return 0;
    };
    let printed_base = printing.power.unwrap_or(0) as i32;
    let _ = player_idx; // silence unused (kept for future log/debug hooks)
    let base = obj
        .ueot_base_pt_override()
        .map(|(p, _)| p)
        .or_else(|| obj.ueot_becomes_land_creature_pt().map(|(p, _)| p))
        .unwrap_or(printed_base);
    let bonus = obj.ueot_power_bonus();
    let effective = base + bonus;
    effective.clamp(i16::MIN as i32, i16::MAX as i32) as i16
}

/// **Round-53 §2 fix — effective-power snapshot for the round-31
/// `Effect::DoubleTargetCreaturesPowerUEOT` (Mightform Harmonizer
/// landfall) resolve arm.**
///
/// Returns the target creature's CURRENT effective power as the
/// number to double, computed to MATCH Python's source-of-truth
/// `DoubleTargetCreaturesPowerUEOT.resolve` (`pump.py:234`), which
/// snapshots `mtg_bot.game.effective_power(state, obj)` =
/// `_compute_effective_pt` (game.py:2138).
///
/// **Why this exists / what it fixes.** The round-31 resolve arm
/// snapshotted via `read_battlefield_creature_power`, which
/// DELIBERATELY omits `obj.counters` (a pinned combat-side
/// asymmetry — see the comment at `state_ops_combat.rs:551-556`).
/// Python's `_compute_effective_pt` FOLDS IN the signed +1/+1 net at
/// game.py:2251 (`p += obj.plus_one_counters - obj.minus_one_counters`).
/// So on a target carrying +1/+1 counters the round-31 Rust arm
/// doubled BASE power while Python doubled EFFECTIVE power — a real
/// §2 silent mistranslation, latent only because the round-31/36
/// genuine Mightform probe staged a counter-free creature
/// (`docs/SEARCH_LIMITATIONS.md`, round-53 entry). On a 3/3 with
/// +2/+2 counters: pre-fix Rust doubled 3, Python doubled 5.
///
/// **The fix.** This helper composes
/// `base (UEOT-SetBasePT override / manland / printed)
///  + ueot_power_bonus()  + obj.counters`
/// where `obj.counters` (signed i32) is Rust's analogue of Python's
/// `plus_one_counters - minus_one_counters` (the SBA path at
/// `state_ops_sba.rs:200` uses exactly `base + obj.counters +
/// ueot_*_bonus()` — same composition, confirming the mapping). The
/// round-31 arm now reads through here, so BOTH engines double the
/// SAME effective-power snapshot.
///
/// **Documented residual (SEARCH_LIMITATIONS).** Layer-7c static
/// anthems and layer-7e P/T switches are NOT folded here (nor by the
/// combat-side reader, nor reachable by any bridge-correct Mightform
/// Harmonizer scenario — the card has no anthem/switch rider and the
/// genuine probe stages none). Same established combat-side
/// asymmetry; documented alongside the round-53 SEARCH_LIMITATIONS
/// entry.
fn read_doubling_power(state: &GameState, obj_id: u32) -> i32 {
    let mut found: Option<&GameObject> = None;
    for player in state.players.iter() {
        if let Some(obj) =
            player.battlefield.iter().find(|o| o.id == obj_id)
        {
            found = Some(obj);
            break;
        }
    }
    let Some(obj) = found else {
        return 0;
    };
    let Some(printing) =
        state.registry.printings.get(obj.printing_id as usize)
    else {
        return 0;
    };
    let printed_base = printing.power.unwrap_or(0) as i32;
    let base = obj
        .ueot_base_pt_override()
        .map(|(p, _)| p)
        .or_else(|| {
            obj.ueot_becomes_land_creature_pt().map(|(p, _)| p)
        })
        .unwrap_or(printed_base);
    base + obj.ueot_power_bonus() + obj.counters
}

/// **BLOCKED-RUST-EFFECT slice (round 54) — Famished Worldsire ETB
/// source-power read.**
///
/// Returns the source creature's CURRENT effective power = `X` in
/// "look at the top X cards of your library, where X is this
/// creature's power". Computed to MATCH Python's source-of-truth
/// `FamishedWorldsireETBEffect.resolve` (`effects/bespoke.py:116`),
/// which reads `mtg_bot.game.effective_power(state, source)` =
/// `_compute_effective_pt` (`game.py:2138`). Famished Worldsire's
/// Devour rider seeds +1/+1 counters as it enters, so the read MUST
/// fold in `obj.counters` — a base-power read would be a real §2
/// silent mistranslation (same class the round-53 Mightform fix
/// closed).
///
/// **Composition (per-slice file-isolation: re-derived here rather
/// than cross-calling `read_doubling_power`).**
/// `base (UEOT-SetBasePT override / manland / printed)
///  + ueot_power_bonus()  + obj.counters`
/// — `obj.counters` (signed i32) is Rust's analogue of Python's
/// `plus_one_counters - minus_one_counters` (`game.py:2251`); the SBA
/// path at `state_ops_sba.rs:200` uses the SAME composition,
/// confirming the mapping. Source not on a battlefield → 0 (matches
/// Python's `if source is None: return` short-circuit chained with
/// `if x <= 0: return`).
///
/// **Documented residual (SEARCH_LIMITATIONS, round-54 entry).**
/// Layer-7c static anthems and layer-7e P/T switches are NOT folded
/// here (same established combat-side / round-53 asymmetry); no
/// bridge-correct Famished Worldsire scenario reaches them (the card
/// has no anthem/switch rider and the genuine probe stages none).
fn read_famished_source_power(state: &GameState, obj_id: u32) -> i32 {
    let mut found: Option<&GameObject> = None;
    for player in state.players.iter() {
        if let Some(obj) =
            player.battlefield.iter().find(|o| o.id == obj_id)
        {
            found = Some(obj);
            break;
        }
    }
    let Some(obj) = found else {
        return 0;
    };
    let Some(printing) =
        state.registry.printings.get(obj.printing_id as usize)
    else {
        return 0;
    };
    let printed_base = printing.power.unwrap_or(0) as i32;
    let base = obj
        .ueot_base_pt_override()
        .map(|(p, _)| p)
        .or_else(|| {
            obj.ueot_becomes_land_creature_pt().map(|(p, _)| p)
        })
        .unwrap_or(printed_base);
    base + obj.ueot_power_bonus() + obj.counters
}

/// Push `amount` damage onto the battlefield creature's per-instance
/// `damage` marker (saturating add into i16). Routes through
/// `Arc::make_mut` on the containing battlefield Vec to preserve CoW.
/// Walks both players' battlefields; returns silently on unknown ids
/// (silent no-op convention, mirrors the public `state.deal_damage`
/// behavior).
///
/// Inlines `state_ops_damage::deal_damage` because that helper is
/// module-private (per the per-slice file-isolation rule). The two
/// implementations match: monotonic accumulation on the marker,
/// saturating into i16, no SBA-firing inline. Used by the
/// FightTargetCreatureWithTargetCreature resolve arm to apply both
/// sides of the simultaneous-damage exchange (CR 701.12).
fn apply_damage_marker(state: &mut GameState, obj_id: u32, amount: i16) {
    if amount <= 0 {
        return;
    }
    for player in state.players.iter_mut() {
        if player.battlefield.iter().any(|o| o.id == obj_id) {
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut player.battlefield);
            for obj in zone.iter_mut() {
                if obj.id == obj_id {
                    obj.damage = obj.damage.saturating_add(amount);
                    return;
                }
            }
        }
    }
}

/// **BLOCKED-RUST-EFFECT slice — Faller's Faithful ETB.**
/// Destroy the source-controller's opponent's first battlefield
/// creature (the `defender = 1 - controller` bf[0] first-slice
/// deterministic pick, identical to the `DestroyTarget { AnyCreature }`
/// arm), then — iff that creature carried NO marked damage at the
/// moment of resolution (`obj.damage == 0`, the byte-equal Rust read
/// of Python's `not obj.damaged_this_turn` for the realistic
/// no-prior-damage ETB) — the victim's controller draws `draw_amount`
/// cards (CR 121.1 — the printed text gives the draw to the destroyed
/// creature's controller).
///
/// Mirrors the `DestroyTarget { AnyCreature }` resolve body verbatim
/// (controller resolution, indestructible-suppress CR 702.12, zone-
/// change reset CR 400.7, Void LTB nonland flag, LTB fan-out via
/// `pending_leaves_dispatches` + `queue_token_cease`) so the destroy
/// half stays byte-equal with the existing destroy substrate; the
/// only additions are the pre-destroy `was_undamaged` snapshot, the
/// victim-controller capture, and the post-destroy conditional draw
/// (inlined draw loop — same shape as `Effect::DrawCards`,
/// re-derived here per the per-slice file-isolation rule rather than
/// cross-calling the DrawCards arm). Empty defender bf / indestructible
/// target = silent fizzle, and the draw rider does NOT run in either
/// fizzle case (CR 608.2c — the "up to one" optional shape resolves
/// as a no-op).
fn destroy_first_defender_creature_then_draw_if_undamaged(
    state: &mut GameState,
    draw_amount: i32,
) {
    let controller = state
        .current_resolve_source_controller
        .map(|c| c as usize)
        .unwrap_or(state.active_player as usize);
    let defender = 1 - controller;
    let bf = &state.players[defender].battlefield;
    if bf.is_empty() {
        return; // fizzle silently — "up to one" no-op, no draw
    }
    let target_id = bf[0].id;
    // Snapshot the undamaged condition BEFORE any mutation: leaving
    // the battlefield resets `obj.damage`, so the read must happen
    // now (mirrors Python's `was_undamaged = not obj.damaged_this_turn`
    // captured before `destroy()` in DestroyTargetCreature.resolve).
    let was_undamaged = bf[0].damage == 0;
    // The victim's controller (defender in the 2-player first slice;
    // == owner). The draw goes here per the printed text, not to the
    // spell's controller. Mirrors Python's
    // `victim_controller_id = obj.controller_id`.
    let victim_controller = defender;
    // Indestructible check (CR 702.12): peek the target's printing
    // keywords before mutating. Suppress destroy AND draw silently if
    // present (Python's turn.destroy carries the same gate; the rider
    // only runs alongside an actual destruction).
    let target_printing_id = bf[0].printing_id;
    let is_indestructible = match state.registry.lookup(target_printing_id) {
        Some(printing) => printing
            .keywords
            .iter()
            .any(|k| k == "indestructible"),
        None => false,
    };
    if is_indestructible {
        return; // CR 702.12 — suppress silently, no draw
    }
    // Pop from defender's battlefield (CoW-safe).
    let bf_mut: &mut Vec<GameObject> =
        Arc::make_mut(&mut state.players[defender].battlefield);
    let pos = bf_mut
        .iter()
        .position(|o| o.id == target_id)
        .expect("target_id was bf[0] but not found on re-scan");
    let mut obj = bf_mut.remove(pos);
    // Zone-change reset (CR 400.7) — identical to the DestroyTarget
    // arm. summoning_sick deliberately NOT reset (Python's
    // turn.move_off_battlefield omits the clear — CR 302.1, see I35).
    obj.zone = ZONE_GRAVEYARD;
    obj.tapped = false;
    obj.damage = 0;
    obj.counters = 0;
    obj.attached_to = None;
    obj.exiled_with_source = None;
    let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
    Arc::make_mut(&mut state.players[defender].graveyard).push(obj);
    // Round-29 Void LTB tracking: destroy is a battlefield exit.
    mark_left_battlefield_if_nonland(state, printing_id);
    // LTB fan-out — queue the leaving id; the drain runs in
    // `resolve_top_of_stack` AFTER the resolving slot pops (same
    // deferral shape as the DestroyTarget arm).
    state.pending_leaves_dispatches.push(leaving_obj_id);
    crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
    // Faller's Faithful draw rider: iff the target carried no marked
    // damage at resolve time, the victim's controller draws
    // `draw_amount` cards. Negative clamps to 0 (X-from-count zero
    // short-circuit convention). Inlined draw loop — same pattern as
    // `Effect::DrawCards`.
    let n = draw_amount.max(0) as usize;
    if was_undamaged && n > 0 {
        for _ in 0..n {
            let player = &mut state.players[victim_controller];
            let lib = Arc::make_mut(&mut player.library);
            if lib.is_empty() {
                // CR 704.5b — empty-library draw flags the player.
                player.attempted_draw_on_empty = true;
                break;
            }
            let mut drawn = lib.remove(0);
            drawn.zone = ZONE_HAND;
            Arc::make_mut(&mut player.hand).push(drawn);
        }
    }
}

/// **BLOCKED-RUST-EFFECT slice (round 60) — Perigee Beckoner target
/// pick.** Resolve the source's controller by scanning every tracked
/// zone for `source_obj_id` (identical to the bare
/// `Effect::PumpTargetCreatureUntilEOT` arm's source-controller
/// search — Perigee is its `granted_triggered_ability`-carrying
/// sibling, so the controller resolution must match exactly), then
/// return `(controller_idx, target_id)` for the FIRST creature on
/// that controller's battlefield whose id is NOT `source_obj_id`
/// (Perigee's "ANOTHER target creature you control" — CR 115.4
/// "another" excludes the source itself; mirrors Python's
/// `PumpTargetCreatureUntilEOT(exclude_self=True)` dropping
/// `state.resolving_source` from `legal_targets`).
///
/// Returns `None` when the source is untrackable (silent fizzle) or
/// the controller controls no OTHER creature (Perigee's ETB is a
/// non-`optional` "another target creature you control" — with no
/// legal target the trigger still resolves but does nothing, CR
/// 608.2b; observationally a silent no-op, matching Python's
/// `if not legal_targets: return`).
///
/// Creature-ness gates on the printing's `card_types` containing
/// "Creature" — the canonical creature-detection pattern shared with
/// the bare pump arm (state_ops_cast.rs:304 / state_ops_legal.rs:571).
fn perigee_pick_another_own_creature(
    state: &GameState,
    source_obj_id: u32,
) -> Option<(usize, u32)> {
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
    let controller = src_controller?;
    let cidx = controller as usize;
    let bf = &state.players[cidx].battlefield;
    let registry = &state.registry;
    let target_id = bf.iter().find_map(|obj| {
        if obj.id == source_obj_id {
            return None; // CR 115.4 "another" — exclude the source
        }
        let printing = registry.printings.get(obj.printing_id as usize)?;
        if printing.card_types.iter().any(|t| t == "Creature") {
            Some(obj.id)
        } else {
            None
        }
    })?;
    Some((cidx, target_id))
}

fn apply_effect(
    state: &mut GameState,
    effect: &Effect,
    source_obj_id: u32,
) -> PyResult<()> {
    match effect {
        Effect::DealDamage { amount, target } => {
            // **Controller-of-effect fix (DealDamage defender).** The
            // defender is the OPPONENT of the SOURCE's controller, not
            // the opponent of `active_player`. CR 119.5 / 608.2: an
            // effect resolves under its source's controller; the
            // first-slice "target = the defending player" deterministic
            // pick must be relative to the resolving spell's
            // controller, not whichever player happens to have priority
            // at resolve time. Pre-fix Rust hardcoded
            // `defender = 1 - state.active_player`, which is wrong when
            // the resolving spell / triggered ability has a controller
            // != active_player. Example: on p0's turn, p1 casts a
            // Lightning Bolt — pre-fix the damage went to p1
            // (1 - active_player = 1 - 0 = 1), not p0. Same fix shape
            // as I59 (DrawCards) and I60 (GainLife); reads the same
            // `current_resolve_source_controller` transient slot, then
            // derives `defender = 1 - source_controller`.
            //
            // Mirrors Python's `DealDamageTargetPlayer` /
            // `DealDamageAnyTarget` deterministic-defender pick at
            // `effects/generic/damage.py`, which uses the source's
            // controller as the choosing player.
            let source_controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
            let defender: u8 = 1 - source_controller;
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
        // cards. Controller resolution: prefer the transient
        // `state.current_resolve_source_controller` (set by
        // `apply_effect_pub_with_controller` / by the stack resolver
        // around `apply_effect` calls — see the DrawCards
        // controller-of-effect fix), falling back to
        // `state.active_player` for back-compat with every direct
        // `apply_effect_pub` caller that hasn't migrated.
        //
        // **Why the fix.** Pre-fix this arm hardcoded
        // `state.active_player`, which is wrong when the resolving
        // spell / triggered ability has a controller != the active
        // player. Example: on player 0's turn, player 1 casts an
        // instant DrawCards-1 in response — pre-fix the card went
        // into PLAYER 0's hand (active_player), not player 1's
        // hand. Mirrors Python's `DrawCards.resolve(state,
        // controller_id, targets)` (effects/generic/draw_mill.py:213)
        // which receives the source's controller explicitly.
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
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            let n = (*count).max(0) as usize;
            for _ in 0..n {
                let player = &mut state.players[controller];
                let lib = Arc::make_mut(&mut player.library);
                if lib.is_empty() {
                    // CR 704.5b — empty-library draw flags the player.
                    player.attempted_draw_on_empty = true;
                    break;
                }
                // Post-CE3: top of library = lib[0].
                let mut obj = lib.remove(0);
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
        //
        // **Controller resolution (post-I59 follow-up — I60)**:
        // prefer the transient
        // `state.current_resolve_source_controller` (set by the
        // stack resolver around each `apply_effect` call), falling
        // back to `state.active_player` for back-compat with every
        // direct `apply_effect_pub` caller that hasn't migrated.
        // Same pattern as `Effect::DrawCards` above — GainLife
        // resolves to the SOURCE's controller per CR 119.5 /
        // 608.2, NOT necessarily the active player. Mirrors
        // Python's `GainLife.resolve(state, controller_id, ...)`
        // at `effects/generic/life.py:33`. The example failure
        // mode pre-fix: on p0's turn, p1's Germinating Wurm
        // (ETB → you gain 2 life) ETBs (perhaps because p1 cast
        // it on its own end-of-turn step that got skipped, or
        // because of a more-exotic timing), trigger fires with
        // controller=p1 — pre-fix p0 gained the 2 life, post-fix
        // p1 does.
        Effect::GainLife { amount } => {
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
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
                // **Controller resolution (I76 follow-up to the
                // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 /
                // I69 / I70 / I71 / I72 / I73 / I74 / I75 controller-
                // of-effect substrate).** CR 119.5 / 608.2: an effect
                // resolves under its source's controller.
                // ReturnToHand's first-slice AnyCreature shortcut
                // picks the SOURCE'S controller's opponent's bf[0],
                // where defender = 1 - controller. Sibling closure
                // to I70 ExileTarget / I75 DestroyTarget — identical
                // target selection path (bf[0] of defender),
                // identical LTB fan-out via
                // pending_leaves_dispatches. Differs from I70 / I75
                // only in destination zone (defender's HAND vs
                // exile / graveyard).
                //
                // **Why the fix.** Pre-fix this arm computed
                // `defender = 1 - state.active_player`. Wrong when
                // the resolving spell / triggered ability has a
                // controller != active_player. Example: on p0's
                // turn, p1 casts an Unsummon-shape instant — pre-
                // fix it self-bounced p1's own bf[0] back to p1's
                // hand (defender = 1 - active_player = 1 - 0 = 1).
                // Post-fix it correctly bounces p0's bf[0] back to
                // p0's hand (the source's controller's opponent —
                // standard Unsummon / Boomerang / Vapor Snag shape).
                //
                // **First-slice owner-vs-controller convention
                // preserved.** Target's controller == owner, so the
                // bounce destination is the defender's hand (where
                // the target's owner's hand lives). The controller
                // fix only changes which side that defender refers
                // to; the destination-is-defender's-hand semantics
                // are unchanged.
                //
                // **LTB fan-out preserved** — leaving id still
                // pushes onto `pending_leaves_dispatches` so the
                // drain runs in `resolve_top_of_stack` AFTER the
                // resolving slot pops.
                let controller = state
                    .current_resolve_source_controller
                    .map(|c| c as usize)
                    .unwrap_or(state.active_player as usize);
                let defender = 1 - controller;
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
                // CE13 closure: `summoning_sick` is NOT reset here.
                // Python's `turn.move_off_battlefield` deliberately
                // omits the clear (CR 302.1 — sickness is battlefield-
                // only state; preserving the flag in non-battlefield
                // zones has no gameplay impact, and the re-ETB path
                // restamps `sick=true`). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
                Arc::make_mut(&mut state.players[defender].hand).push(obj);
                // Round-29 Void LTB tracking: bounce is a battlefield-
                // exit. Flag flips iff the bounced object is nonland.
                mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
            }
        },
        // Round-10: Mill. Caller's controller puts the top `count`
        // cards of their library into their graveyard. "Top" is
        // lib[0] post-CE3 (mirrors zones convention used by
        // DrawCards above).
        //
        // **Controller resolution (I65 follow-up to the I59 / I60 /
        // I63 / I64 controller-of-effect substrate).** Prefer the
        // transient `state.current_resolve_source_controller` (set
        // by the stack resolver around each `apply_effect` call),
        // falling back to `state.active_player` for back-compat
        // with direct `apply_effect_pub` callers. Same pattern as
        // `Effect::DrawCards` / `Effect::GainLife` /
        // `Effect::DamageEachOpponent` / `Effect::DealDamage` —
        // CR 119.5 / 608.2: an effect resolves under its source's
        // controller. For Mill (self-mill), the milling player is
        // the SOURCE'S controller, not the active player.
        //
        // **Why the fix.** Pre-fix this arm hardcoded
        // `state.active_player`. Wrong when the resolving spell /
        // triggered ability has a controller != active_player.
        // Example: on p0's turn, p1 casts an instant Mill-2 self-
        // mill in response (e.g. a graveyard-fueling reactive
        // spell) — pre-fix the cards left p0's library (active_-
        // player), post-fix they leave p1's library (the spell's
        // controller). Mirrors Python's analogous self-mill
        // handling (drawn off `MillTargetPlayer` with target =
        // controller; the Rust `Effect::Mill` arm is the
        // controller-target shortcut).
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
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            let n = (*count).max(0) as usize;
            for _ in 0..n {
                let player = &mut state.players[controller];
                let lib = Arc::make_mut(&mut player.library);
                if lib.is_empty() {
                    break; // empty library — silent stop
                }
                // Always remove index 0 — top after each prior remove.
                let mut obj = lib.remove(0);
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
            // **Controller resolution (I77 follow-up to the
            // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 / I69 /
            // I70 / I71 / I72 / I73 / I74 / I75 / I76 controller-of-
            // effect substrate).** CR 119.5 / 608.2: an effect
            // resolves under its source's controller. MillTargetPlayer's
            // first-slice deterministic target picker chooses the
            // SOURCE'S controller's opponent (= the source's other
            // player), where target_idx = 1 - controller.
            //
            // **Why the fix.** Pre-fix this arm computed
            // `target_idx = 1 - state.active_player`. Wrong when the
            // resolving spell / triggered ability has a controller
            // != active_player. Example: on p0's turn, p1 casts a
            // Scrabbling-Skullcrab-shape "target player mills 2"
            // instant — pre-fix it self-milled p1's own library
            // (target_idx = 1 - active_player = 1 - 0 = 1).
            // Post-fix it correctly mills p0's library (the source's
            // controller's opponent — standard Mind Funeral / Tome
            // Scour shape).
            //
            // Sibling closure to I65 Mill (self-mill, where controller
            // mills their own library) — I65 routes to controller,
            // I77 routes to (1 - controller). Both close the
            // active_player-vs-source's-controller divergence; they
            // differ only in WHICH side mills (self vs target-player).
            //
            // (Real target-player choice plumbing remains deferred
            // — mirrors existing single-target first-slice
            // conventions.)
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            let target_idx = 1 - controller;
            let library_mut = Arc::make_mut(&mut state.players[target_idx].library);
            let n_to_mill = (*count as usize).min(library_mut.len());
            if n_to_mill == 0 {
                // count=0 OR empty target library — silent no-op.
            } else {
                // Post-CE3: top of library = lib[0]. Remove from head
                // n_to_mill times.
                let mut milled: Vec<GameObject> = Vec::with_capacity(n_to_mill);
                for _ in 0..n_to_mill {
                    milled.push(library_mut.remove(0));
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
        // BLOCKED-RUST-EFFECT slice (round 42) -- mill an opponent
        // a number of cards equal to the source-controller's current
        // life total. Sister of round-32 / 35 / 36 / 37 (damage
        // substrate), round-33 (counters substrate), and round-34
        // (surveil substrate) -- same dynamic-X-from-count plumbing,
        // NEW apply substrate (mill-target-player) AND NEW denominator
        // axis (source-controller's life total). Mirrors Python's
        // `MillTargetPlayer(use_controller_life=True)`
        // (`draw_mill.py:151` -- Space-Time Anomaly's instant
        // resolution).
        //
        // **Source-controller resolution.** Uses
        // `current_resolve_source_controller` (mirrors the existing
        // `Effect::MillTargetPlayer` arm's I77 post-fix pattern at
        // state_ops_resolve.rs:1199 — both mill arms route through
        // the same controller-of-effect substrate). Fallback to
        // `state.active_player` if unset (matches the existing
        // MillTargetPlayer arm's defensive fallback for trigger
        // shapes where the source-controller wasn't seeded).
        //
        // **Life-total denominator.** `state.players[controller].life`
        // is i32; `max(0, life)` clamps negative life totals
        // (arbitrary lose-life-past-zero / infect-style scenarios)
        // to zero — silent no-op, matching Python's
        // `n = max(0, state.player_by_id(controller_id).life)`
        // clamp at draw_mill.py:187.
        //
        // **Apply / fizzle.** Bit-equal to the `MillTargetPlayer`
        // arm's pop-N + push-to-graveyard logic: take from lib[0]
        // (post-CE3 top-of-library convention), reset per-object
        // state on graveyard move (CR 400.7), stop early on empty
        // library mid-mill (matches Python's `if not target.library:
        // break`). Target player = `1 - controller` (first-slice
        // deterministic single-opponent pick; mirrors the existing
        // MillTargetPlayer arm's defender-pick).
        //
        // **Inlining note.** Same E0624 cross-file `#[pymethods]`
        // friction as the existing MillTargetPlayer arm — re-inlines
        // the pop-N + push-to-graveyard logic instead of routing
        // through state_ops_library.rs's mill_target_player primitive.
        Effect::MillTargetPlayerEqualToYourLifeTotal => {
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            // Life-total denominator: clamp negative life to 0
            // (matches Python's `max(0, life)` clamp).
            let life = state.players[controller].life;
            let count = life.max(0) as usize;
            if count == 0 {
                // life <= 0 -> silent no-op (count = 0).
                return Ok(());
            }
            let target_idx = 1 - controller;
            let library_mut = Arc::make_mut(&mut state.players[target_idx].library);
            let n_to_mill = count.min(library_mut.len());
            if n_to_mill == 0 {
                // empty target library — silent no-op (mid-mill empty
                // is the same shape via the loop break below, but
                // pre-check saves an Arc::make_mut churn).
                return Ok(());
            }
            // Post-CE3: top of library = lib[0]. Remove from head
            // n_to_mill times. Mirrors the round-19 MillTargetPlayer
            // arm's pop-N shape bit-for-bit (only the count source
            // differs — dynamic from life vs static from variant
            // field).
            let mut milled: Vec<GameObject> = Vec::with_capacity(n_to_mill);
            for _ in 0..n_to_mill {
                milled.push(library_mut.remove(0));
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
                // **Controller resolution (I70 follow-up to the
                // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 /
                // I69 controller-of-effect substrate).** Prefer
                // the transient `state.current_resolve_source_-
                // controller`, falling back to `state.active_-
                // player`. Same pattern as `Effect::DealDamage`
                // (I64) / `Effect::DealDamageAnyTarget` (I67) —
                // CR 119.5 / 608.2: an effect resolves under its
                // source's controller. The "AnyCreature" first-
                // slice target shortcut picks the FIRST creature
                // on the DEFENDING side — where defender = the
                // SOURCE'S controller's opponent.
                //
                // **Why the fix.** Pre-fix this arm computed
                // `defender = 1 - state.active_player`. Wrong when
                // the resolving spell / triggered ability has a
                // controller != active_player. Example: on p0's
                // turn, p1 casts an Exile-target-creature instant
                // — pre-fix it exiled p1's own first creature
                // (defender = 1 - active_player = 1 - 0 = 1),
                // self-exiling. Post-fix it correctly exiles p0's
                // first creature (the source's controller's
                // opponent).
                let controller = state
                    .current_resolve_source_controller
                    .map(|c| c as usize)
                    .unwrap_or(state.active_player as usize);
                let defender = 1 - controller;
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
                // CE13 closure: `summoning_sick` is NOT reset here.
                // Python's `turn.move_off_battlefield` deliberately
                // omits the clear (CR 302.1 — sickness is battlefield-
                // only state). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
                Arc::make_mut(&mut state.players[defender].exile).push(obj);
                // Round-29 Void LTB tracking: exile is a battlefield-
                // exit. Flag flips iff the exiled object is nonland.
                mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
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
                // **Controller resolution (I71 follow-up to the
                // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 /
                // I69 / I70 controller-of-effect substrate).**
                // Same pattern as I70 ExileTarget — CR 119.5 /
                // 608.2: an effect resolves under its source's
                // controller. "AnyCreature" first-slice target
                // shortcut picks the FIRST object on the
                // DEFENDING side, where defender = the SOURCE'S
                // controller's opponent.
                //
                // **Why the fix.** Pre-fix this arm computed
                // `defender = 1 - state.active_player`. Wrong when
                // the resolving spell / triggered ability has a
                // controller != active_player. Example: on p0's
                // turn, p1 casts a Twiddle-shape tap instant —
                // pre-fix it tapped p1's own bf[0] (self-tap).
                // Post-fix it correctly taps p0's bf[0] (the
                // source's controller's opponent).
                let controller = state
                    .current_resolve_source_controller
                    .map(|c| c as usize)
                    .unwrap_or(state.active_player as usize);
                let defender = 1 - controller;
                let bf = &state.players[defender].battlefield;
                if bf.is_empty() {
                    return Ok(()); // fizzle silently
                }
                let target_id = bf[0].id;
                // Round-58 BECOMES_TAPPED event bridge — tapper-
                // effect site. Python's TapTarget-family effects
                // (`effects/generic/tap.py`'s TapTarget /
                // TapAnotherTargetCreature etc., plus
                // `effects/combinators.py:163` and
                // `effects/bespoke.py:496`) all route the actual tap
                // through `turn.tap_permanent`, which fires
                // `Event.BECOMES_TAPPED` for the tapped target — and
                // ONLY when the target was untapped (Python's
                // `tap_permanent` no-ops on an already-tapped
                // permanent: no re-stamp, no event). Route through
                // the centralized chokepoint so the no-op-if-already-
                // tapped gate matches Python exactly (an already-
                // tapped target is a silent no-op with NO
                // BECOMES_TAPPED dispatch — byte-equal to Python's
                // early return).
                crate::state_ops_resolve::tap_permanent_and_dispatch(
                    state, target_id,
                )?;
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
                // **Controller resolution (I72 follow-up to the
                // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 /
                // I69 / I70 / I71 controller-of-effect substrate).**
                // Same pattern as I71 TapTarget — CR 119.5 /
                // 608.2: an effect resolves under its source's
                // controller. "AnyCreature" first-slice target
                // shortcut picks the FIRST object on the
                // DEFENDING side, where defender = the SOURCE'S
                // controller's opponent.
                //
                // **Why the fix.** Pre-fix this arm computed
                // `defender = 1 - state.active_player`. Wrong when
                // the resolving spell / triggered ability has a
                // controller != active_player. Example: on p0's
                // turn, p1 casts a Twiddle-shape untap instant —
                // pre-fix it untapped p1's own bf[0] (self-untap).
                // Post-fix it correctly untaps p0's bf[0] (the
                // source's controller's opponent).
                let controller = state
                    .current_resolve_source_controller
                    .map(|c| c as usize)
                    .unwrap_or(state.active_player as usize);
                let defender = 1 - controller;
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
                // **Controller resolution (I66 follow-up to the I59 /
                // I60 / I63 / I64 / I65 controller-of-effect
                // substrate).** Prefer the transient
                // `state.current_resolve_source_controller` (set by
                // the stack resolver around each `apply_effect` call),
                // falling back to `state.active_player` for back-
                // compat with direct `apply_effect_pub` callers. Same
                // pattern as `Effect::DrawCards` / `Effect::GainLife`
                // / `Effect::DamageEachOpponent` / `Effect::DealDamage`
                // / `Effect::Mill` — CR 119.5 / 608.2: an effect
                // resolves under its source's controller. For
                // Sacrifice (the "you sacrifice" arm), the
                // sacrificing player is the SOURCE'S controller, not
                // the active player.
                //
                // **Why the fix.** Pre-fix this arm hardcoded
                // `state.active_player`. Wrong when the resolving
                // spell / triggered ability has a controller !=
                // active_player. Example: on p0's turn, p1 casts an
                // instant Altar's-Reap-shape spell ("sacrifice a
                // creature, draw two cards") — pre-fix the spell
                // sacrificed p0's first battlefield permanent
                // (active_player), post-fix it correctly sacrifices
                // p1's (the spell's controller).
                let controller = state
                    .current_resolve_source_controller
                    .map(|c| c as usize)
                    .unwrap_or(state.active_player as usize);
                let bf = &state.players[controller].battlefield;
                if bf.is_empty() {
                    return Ok(()); // fizzle silently
                }
                let target_id = bf[0].id;
                // Pop from sacrificing player's battlefield. Use
                // Arc::make_mut for CoW safety.
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[controller].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id was bf[0] but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                // Stamp graveyard zone + reset per-object state. First-
                // slice: target's controller == owner, so push onto
                // sacrificing player's graveyard (where the sacrificed
                // permanent's owner lives).
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                // CE13 closure: `summoning_sick` is NOT reset here.
                // Python's `turn.move_off_battlefield` deliberately
                // omits the clear (CR 302.1 — sickness is battlefield-
                // only state). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
                Arc::make_mut(&mut state.players[controller].graveyard).push(obj);
                // Round-29 Void LTB tracking: sacrifice is a
                // battlefield-exit. Flag flips iff sac'd object is nonland.
                mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
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
                // **Controller resolution (I73 follow-up to the
                // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 /
                // I69 / I70 / I71 / I72 controller-of-effect
                // substrate).** Same pattern as I71 TapTarget /
                // I72 UntapTarget — CR 119.5 / 608.2: an effect
                // resolves under its source's controller.
                // "AnyCreature" first-slice target shortcut picks
                // the FIRST object on the DEFENDING side, where
                // defender = the SOURCE'S controller's opponent.
                //
                // **Why the fix.** Pre-fix this arm computed
                // `defender = 1 - state.active_player`. Wrong when
                // the resolving spell / triggered ability has a
                // controller != active_player. Example: on p0's
                // turn, p1 casts a +1/+1-counter instant — pre-fix
                // it self-buffed p1's own bf[0]; post-fix it
                // correctly places the counter on p0's bf[0]
                // (the source's controller's opponent, mirroring
                // the bounce / exile / tap / untap defender
                // convention).
                let controller = state
                    .current_resolve_source_controller
                    .map(|c| c as usize)
                    .unwrap_or(state.active_player as usize);
                let defender = 1 - controller;
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
                // **Controller resolution (I74 follow-up to the
                // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 /
                // I69 / I70 / I71 / I72 / I73 controller-of-effect
                // substrate).** CR 119.5 / 608.2: an effect
                // resolves under its source's controller. Mind-Rot-
                // shape "target player discards a card" first-slice
                // target shortcut picks the SOURCE'S controller's
                // opponent (defender), where defender = 1 -
                // controller.
                //
                // **Why the fix.** Pre-fix this arm computed
                // `defender = 1 - state.active_player`. Wrong when
                // the resolving spell / triggered ability has a
                // controller != active_player. Example: on p0's
                // turn, p1 casts a Mind-Rot-shape instant — pre-
                // fix it self-milled p1's own hand[0]; post-fix
                // it correctly discards p0's hand[0] (the source's
                // controller's opponent — matching the convention
                // that AnyPlayer-on-discard means "target opponent
                // discards", a first-slice approximation of the
                // real "target player choice" surface).
                let controller = state
                    .current_resolve_source_controller
                    .map(|c| c as usize)
                    .unwrap_or(state.active_player as usize);
                let defender = 1 - controller;
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
                // **Controller resolution (I75 follow-up to the
                // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 /
                // I69 / I70 / I71 / I72 / I73 / I74 controller-of-
                // effect substrate).** CR 119.5 / 608.2: an effect
                // resolves under its source's controller.
                // DestroyTarget's first-slice AnyCreature shortcut
                // picks the SOURCE'S controller's opponent's bf[0],
                // where defender = 1 - controller. Sibling closure
                // to I70 ExileTarget — identical target selection
                // path (bf[0] of defender), identical indestructible-
                // suppress gate, identical LTB fan-out via
                // pending_leaves_dispatches. Differs from I70 only
                // in destination zone (graveyard vs exile).
                //
                // **Why the fix.** Pre-fix this arm computed
                // `defender = 1 - state.active_player`. Wrong when
                // the resolving spell / triggered ability has a
                // controller != active_player. Example: on p0's
                // turn, p1 casts a Doom-Blade-shape instant —
                // pre-fix it self-destroyed p1's own bf[0]
                // (defender = 1 - active_player = 1 - 0 = 1).
                // Post-fix it correctly destroys p0's bf[0] (the
                // source's controller's opponent — the standard
                // Murder / Doom Blade / Naturalize removal shape).
                //
                // **Indestructible gate preserved** — the keyword
                // check runs on the resolved defender's bf[0] and
                // still short-circuits silently per CR 702.12.
                //
                // **LTB fan-out preserved** — the leaving id still
                // pushes onto `pending_leaves_dispatches` so the
                // drain runs in `resolve_top_of_stack` AFTER the
                // resolving slot pops, mirroring the
                // pending_etb_dispatches deferral shape.
                let controller = state
                    .current_resolve_source_controller
                    .map(|c| c as usize)
                    .unwrap_or(state.active_player as usize);
                let defender = 1 - controller;
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
                // CE13 closure: `summoning_sick` is NOT reset here.
                // Python's `turn.move_off_battlefield` deliberately
                // omits the clear (CR 302.1 — sickness is battlefield-
                // only state). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
                Arc::make_mut(&mut state.players[defender].graveyard).push(obj);
                // Round-29 Void LTB tracking: destroy is a battlefield-
                // exit. Flag flips iff destroyed object is nonland.
                mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
            }
        },
        // BLOCKED-RUST-EFFECT slice — Faller's Faithful ETB
        // (~14,108 17lands decks). "Destroy up to one OTHER target
        // creature. If that creature wasn't dealt damage this turn,
        // its controller draws `draw_amount` cards." Structural
        // sibling of `DestroyTarget { AnyCreature }` — same defender
        // bf[0] first-slice pick + indestructible gate + LTB fan-out
        // — plus the pre-destroy undamaged snapshot + post-destroy
        // conditional victim-controller draw. Logic lives in the
        // module-private `destroy_first_defender_creature_then_draw_
        // if_undamaged` helper (per the per-slice file-isolation
        // rule). Mirrors Python's
        // `DestroyTargetCreature(draw_if_undamaged_amount=draw_amount,
        // optional=True, exclude_self=True)`
        // (`effects/generic/destroy.py:94`).
        Effect::DestroyTargetCreatureThenDrawIfUndamaged { draw_amount } => {
            destroy_first_defender_creature_then_draw_if_undamaged(
                state, *draw_amount,
            );
        }
        // Round-17: DamageEachOpponent. CR 701.4 + AOE pattern — the
        // controller deals ``amount`` damage to each of their
        // opponents.
        //
        // **Two-player engine: damages the source-controller's
        // opponent.** No explicit target — the controller is the
        // SOURCE's controller (per CR 119.5 / 608.2; mirrors
        // Python's `DealDamageEachOpponent.resolve(state,
        // controller_id, targets)` at
        // `effects/generic/damage.py:152` which iterates
        // `state.players` and skips `p.id == controller_id`). The
        // one opponent is `1 - controller`. Mirrors the I59/I60
        // controller-of-effect pattern: prefer the transient
        // `state.current_resolve_source_controller` (set by the
        // stack resolver around each `apply_effect` call), falling
        // back to `state.active_player` for back-compat with direct
        // `apply_effect_pub` callers.
        //
        // **Why the fix (I62).** Pre-fix this arm hardcoded
        // `1 - state.active_player` as the defender. Wrong when the
        // resolving spell / triggered ability has a controller !=
        // active_player. Example: on p0's turn, p1's creature has
        // an "ETB → deal 2 damage to each opponent" trigger (e.g.
        // a flicker-ETB scenario where the creature blinks back
        // during p0's turn). Pre-fix the trigger damaged p1
        // (active_player=0's opponent = p1), self-damaging the
        // trigger's controller. Post-fix the trigger correctly
        // damages p0 (the SOURCE's opponent).
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
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            let defender = 1 - controller;
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
        //
        // **bf-ETB iteration (I33 closure).** Visit order matches
        // Python's centralized `state.battlefield` walk via the shared
        // `crate::bf_iter::bf_iter_etb_sorted` helper. Outcome is
        // order-invariant for damage marking (each eligible creature
        // gets `+amount` exactly once via the saturating_add), so the
        // observable post-state is identical pre- and post-closure on
        // every existing fixture. The change is pre-emptive: visit
        // order becomes load-bearing when the future trigger emitter
        // (CE8 substrate) walks the same victims to push
        // damage-trigger / death-trigger stack items — at that point
        // the relative emission order must mirror Python's centralized
        // walk for cross-engine smoke parity. See I33 in
        // `docs/RUST_PARITY_GAPS.md`.
        Effect::DamageEachCreature { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "DamageEachCreature amount must be non-negative, got {amount}"
                )));
            }
            let amount_i16 = (*amount).min(i16::MAX as i32) as i16;
            // Collect (controller_idx, obj_id) for every Creature on
            // either bf in bf-ETB-timestamp order, so the per-player
            // mutating pass below applies damage in the same order
            // Python's centralized `state.battlefield` walk emits.
            let victims: Vec<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
                .into_iter()
                .filter_map(|obj| {
                    let printing = state.registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some((obj.controller as usize, obj.id))
                    } else {
                        None
                    }
                })
                .collect();
            if victims.is_empty() {
                return Ok(());
            }
            for (pidx, target_id) in victims {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                        break;
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
            // **Controller resolution (I81 follow-up to the
            // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 / I69 /
            // I70 / I71 / I72 / I73 / I74 / I75 / I76 / I77 / I78 /
            // I79 / I80 controller-of-effect substrate).**
            // CR 119.5 / 608.2 / 111.4: a token is created under the
            // controller of the spell or ability that creates it —
            // which is the SOURCE's controller, not necessarily the
            // active player.
            //
            // **Why the fix.** Pre-fix this arm computed
            // `active = state.active_player`, used both for the
            // token's `controller` field and for which player's
            // battlefield receives the push. Wrong when the resolving
            // spell / triggered ability has a controller !=
            // active_player. Example: on p0's turn, p1 casts a
            // Servo-Schematic-shape instant — pre-fix the tokens
            // entered under p0's control on p0's battlefield
            // (active_player=0); post-fix they correctly enter under
            // p1's control on p1's battlefield. Mirrors Python's
            // `CreateToken.resolve(state, controller_id, targets)`
            // at `effects/generic/tokens.py:202`, which builds the
            // `recipients` list from `[controller_id]` (or every
            // living player when `each_player=True`).
            //
            // Same transient-slot lookup preamble as I59-I80; only
            // the post-resolve consumer differs (the controller
            // value is used for the token's `controller` byte AND
            // for picking the recipient battlefield Vec).
            //
            // Each-player and other token shapes (CreateTokenAndAttachSelf,
            // CreateTokenPerMulticoloredPermanent,
            // CreateTokenCopyOfTargetCreatureYouControl, the Moonlit
            // Meditation replacement, CR 614 token-creation
            // replacements like Exalted Sunborn / Anointed Procession,
            // the end-of-combat-sacrifice flag, the `tapped`/`attacking`
            // flag bundle) are not yet plumbed in this Rust arm — the
            // first-slice surface here is the basic "create N tokens
            // of `token_printing_id` under the controller" shape only.
            // Those richer surfaces still resolve through the Python
            // path; this fix only addresses the active_player-vs-
            // source's-controller divergence for the basic shape.
            let active = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);

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
            //
            // CE4 closure: stamp each token with a fresh
            // etb_timestamp. Multi-token effects produce strictly-
            // monotonic timestamps so the snapshot / fingerprint walk
            // preserves the within-effect creation order while
            // intermixing correctly with timestamps from prior /
            // subsequent ETBs.
            let n_u32 = n as u32; // n is the *count parameter (i32 → usize → u32 safe; count ≥ 0 was validated above)
            let bf_etb_base = state.next_etb_timestamp;
            state.next_etb_timestamp = state.next_etb_timestamp.saturating_add(n_u32);
            // ETB-trigger Slice 2 (RS4): collect each fresh token's id
            // so we can dispatch_event(Event::Enters, ...) for each
            // AFTER the bf-push pass releases the player-mut borrow.
            let mut token_ids: Vec<u32> = Vec::with_capacity(n);
            let bf: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[active as usize].battlefield);
            for i in 0..n {
                bf.push(GameObject {
                    id: next_id,
                    printing_id: token_pid,
                    controller: active,
                    zone: ZONE_BATTLEFIELD,
                    tapped: false,
                    summoning_sick: true,
                    damage: 0,
                    counters: 0,
                    charge_counters: 0,
                    loyalty_counters: 0,
                    attached_to: None,
                    exiled_with_source: None,
                    // Round-30 stun-counter substrate: tokens enter
                    // with no stun counters per make_object precedent.
                    stun_counters: 0,
                    etb_timestamp: bf_etb_base.saturating_add(i as u32),
                    ueot_modifiers: Vec::new(),
                    // warp_cost substrate (Phase 1, round-63): tokens
                    // are never warp-cast (no warp_cost on a token
                    // printing). Back-compat default.
                    warp_exile_pending: false,
                    warped: false,
                });
                token_ids.push(next_id);
                next_id += 1;
            }
            // ETB-trigger Slice 2 (RS4): queue ENTERS per token in
            // stamp order. Drained by the surrounding resolver after
            // the resolving spell's stack item pops.
            state.pending_etb_dispatches.extend(token_ids);
        }
        // BLOCKED-RUST-EFFECT slice (round 43) -- each living player
        // creates `count` tokens of the given printing under their
        // own control. Sister of the `Effect::CreateToken` arm
        // above; differs only in the recipient set (every living
        // player vs source-controller). Mirrors Python's
        // `CreateToken(each_player=True).resolve` at
        // `effects/generic/tokens.py:202-294` (the `each_player`
        // branch builds `recipients = [p.id for p in state.players
        // if not p.has_lost]` and runs the per-token push loop once
        // per recipient).
        //
        // EoE consumer: Edge Rover (Artifact Creature -- Robot
        // Scout, "When this creature dies, each player creates a
        // Lander token."). Each-player-creates-token is the FIRST
        // each-player token shape in the audit's BLOCKED-RUST-EFFECT
        // residue and the precondition for any future "each player
        // creates X" sister card.
        //
        // **Mechanism -- fanout.** Two-pass: (1) up-front validation
        // (count >= 0, registry hit on the printing id) so an
        // invalid input surfaces BEFORE any state mutation -- a
        // mid-fanout failure would half-give some recipients tokens
        // and corrupt state. (2) For each living player (skip
        // `has_lost == true` per CR 102.5; mirrors Python's
        // `if not p.has_lost` guard at tokens.py:212), allocate a
        // fresh id range and push `count` tokens onto THEIR
        // battlefield Vec (NOT the source-controller's), tagged
        // `controller = recipient_idx`. Recipients are iterated in
        // `state.players` index order (= controller id order),
        // mirroring Python's `for p in state.players` natural order.
        //
        // **ETB timestamps.** Strict per-token monotonic stamps
        // across all recipients combined (recipient0 first, then
        // recipient1, ...). The CE4 ordering invariant -- a single
        // effect's tokens always carry strictly-increasing stamps,
        // regardless of which player ends up owning them -- mirrors
        // the sister `CreateToken` arm's `bf_etb_base + i` loop and
        // matches Python's natural fanout order.
        //
        // **Pending ENTERS dispatch.** Every fresh token (across
        // every recipient) gets queued in
        // `pending_etb_dispatches`. The surrounding resolver fans
        // out ENTERS event dispatch in queue order, which equals
        // (recipient0_tokens..., recipient1_tokens..., ...).
        //
        // **Out-of-scope first-slice riders.** CR 614 token-creation
        // replacements (Anointed Procession, Moonlit Meditation,
        // Exalted Sunborn), the `tapped`/`attacking`/end-of-combat
        // sacrifice flag bundle -- NONE are plumbed here for the
        // same reason the sister `CreateToken` arm defers them: the
        // EoE consumer (Edge Rover -> Lander) doesn't engage any of
        // them, and the Python path still handles those cases for
        // future cards.
        Effect::CreateTokenEachPlayer {
            count,
            token_printing_id,
        } => {
            if *count < 0 {
                return Err(PyValueError::new_err(format!(
                    "CreateTokenEachPlayer count must be non-negative, got {count}"
                )));
            }
            let token_pid = *token_printing_id;
            if state.registry.lookup(token_pid).is_none() {
                return Err(PyValueError::new_err(format!(
                    "token_printing_id {token_pid} not in registry"
                )));
            }
            let n = *count as usize;
            if n == 0 {
                return Ok(()); // legal no-op (mirrors sister CreateToken arm)
            }
            // Pre-pass 1: collect living-recipient indices in
            // `state.players` order. Mirrors Python's
            // `[p.id for p in state.players if not p.has_lost]`.
            let n_players = state.players.len();
            let mut living: Vec<usize> = Vec::with_capacity(n_players);
            for idx in 0..n_players {
                if !state.players[idx].has_lost {
                    living.push(idx);
                }
            }
            if living.is_empty() {
                // No living players (degenerate state) -- silent
                // no-op, mirrors Python's empty-recipients-Vec
                // natural fallthrough.
                return Ok(());
            }
            // Allocate fresh ids: scan every zone on every player
            // for the current max id, allocate starting at max + 1.
            // Mirrors the sister `CreateToken` arm's allocator.
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
            // CE4 closure: stamp each token (across all recipients
            // combined) with a fresh strictly-monotonic etb_timestamp.
            let total_tokens = (n * living.len()) as u32;
            let bf_etb_base = state.next_etb_timestamp;
            state.next_etb_timestamp = state.next_etb_timestamp.saturating_add(total_tokens);
            // Per-token global index so timestamps stay strictly
            // monotonic across the whole fanout.
            let mut global_token_idx: u32 = 0;
            let mut token_ids: Vec<u32> = Vec::with_capacity(total_tokens as usize);
            for recipient_idx in living {
                let recipient_u8 = recipient_idx as u8;
                let bf: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[recipient_idx].battlefield);
                for _ in 0..n {
                    bf.push(GameObject {
                        id: next_id,
                        printing_id: token_pid,
                        controller: recipient_u8,
                        zone: ZONE_BATTLEFIELD,
                        tapped: false,
                        summoning_sick: true,
                        damage: 0,
                        counters: 0,
                        charge_counters: 0,
                        loyalty_counters: 0,
                        attached_to: None,
                        exiled_with_source: None,
                        // Tokens enter with no stun counters per
                        // make_object precedent (round 30).
                        stun_counters: 0,
                        etb_timestamp: bf_etb_base.saturating_add(global_token_idx),
                        ueot_modifiers: Vec::new(),
                        // warp_cost substrate (Phase 1, round-63):
                        // tokens are never warp-cast. Back-compat
                        // default.
                        warp_exile_pending: false,
                        warped: false,
                    });
                    token_ids.push(next_id);
                    next_id += 1;
                    global_token_idx += 1;
                }
            }
            // Queue ENTERS for every fresh token in fanout order
            // (recipient0 first, then recipient1, ...). Mirrors the
            // sister `CreateToken` arm's pending dispatch shape.
            state.pending_etb_dispatches.extend(token_ids);
        }
        // Phase 6 token-printing substrate -- Phase 4 (round 50): the
        // `tapped` create-token rider. Sister of the `Effect::
        // CreateToken` arm above; the ONLY behavioral difference is
        // that every fresh token enters the battlefield TAPPED
        // (`tapped: true` instead of `tapped: false`). Mirrors
        // Python's `CreateToken(tapped=True).resolve` at
        // `effects/generic/tokens.py:286-287` (the `if self.tapped:
        // obj.tapped = True` post-ETB branch -- the token still enters
        // through `put_into_battlefield` so its ETB fires, then is
        // flipped tapped).
        //
        // EoE consumer: Gravpack Monoist (Creature -- Robot, flying;
        // "When this creature dies, create a tapped 2/2 Robot
        // token." -- 25,252 17lands decks). The Robot token is vanilla
        // (no abilities/keywords, 2/2 Artifact Creature), so this
        // variant + the Phase-1 vanilla-token recognizer + the
        // recognizer widen flip Gravpack Monoist drop->admit with NO
        // Phase-3 Lander-activated-ability dependency.
        //
        // **Mechanism (parity with the sister `CreateToken` arm).**
        // Identical to the sister arm -- count>=0 validation, registry
        // bounds check, controller-of-effect resolution
        // (`current_resolve_source_controller`, I81 fix), fresh-id
        // allocator, CE4 monotonic etb_timestamp, summoning_sick=true,
        // pending ENTERS dispatch -- with the SINGLE byte difference
        // that each pushed `GameObject` carries `tapped: true`. The
        // each-player / attacking / schedule-eoc-sac riders are NOT
        // plumbed here for the same reason the sister arm defers them
        // (no EoE consumer of the tapped shape engages them; the
        // Python path still handles those cases for future cards).
        Effect::CreateTokenTapped {
            count,
            token_printing_id,
        } => {
            if *count < 0 {
                return Err(PyValueError::new_err(format!(
                    "CreateTokenTapped count must be non-negative, got {count}"
                )));
            }
            // Registry-bounds check up front so an unknown printing_id
            // surfaces before any state mutation (mirrors the sister
            // `CreateToken` arm's whole-or-nothing validation).
            let token_pid = *token_printing_id;
            if state.registry.lookup(token_pid).is_none() {
                return Err(PyValueError::new_err(format!(
                    "token_printing_id {token_pid} not in registry"
                )));
            }
            let n = *count as usize;
            if n == 0 {
                return Ok(()); // legal no-op (mirrors sister CreateToken arm)
            }
            // Controller resolution: same I81 controller-of-effect
            // substrate as the sister `CreateToken` arm -- both the
            // recipient battlefield Vec pick AND the token's
            // `controller` byte derive from
            // `current_resolve_source_controller` (active_player as the
            // back-compat fallback). Mirrors Python's
            // `CreateToken.resolve(state, controller_id, targets)`
            // building `recipients = [controller_id]`.
            let active = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);

            // Allocate fresh ids: scan every zone on both players for
            // the current max id, allocate starting at max + 1.
            // Mirrors the sister `CreateToken` arm's allocator.
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

            // CE4 closure: stamp each token with a fresh strictly-
            // monotonic etb_timestamp (mirrors the sister arm).
            let n_u32 = n as u32;
            let bf_etb_base = state.next_etb_timestamp;
            state.next_etb_timestamp = state.next_etb_timestamp.saturating_add(n_u32);
            let mut token_ids: Vec<u32> = Vec::with_capacity(n);
            let bf: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[active as usize].battlefield);
            for i in 0..n {
                bf.push(GameObject {
                    id: next_id,
                    printing_id: token_pid,
                    controller: active,
                    zone: ZONE_BATTLEFIELD,
                    // The Phase-4 byte difference vs the sister
                    // `CreateToken` arm: the token enters TAPPED.
                    // (warp_cost substrate marker — see the
                    // warp_exile_pending/warped defaults at this
                    // literal's tail; tokens are never warp-cast.)
                    tapped: true,
                    summoning_sick: true,
                    damage: 0,
                    counters: 0,
                    charge_counters: 0,
                    loyalty_counters: 0,
                    attached_to: None,
                    exiled_with_source: None,
                    stun_counters: 0,
                    etb_timestamp: bf_etb_base.saturating_add(i as u32),
                    ueot_modifiers: Vec::new(),
                    // warp_cost substrate (Phase 1, round-63): tapped
                    // token enters; never warp-cast. Back-compat
                    // default.
                    warp_exile_pending: false,
                    warped: false,
                });
                token_ids.push(next_id);
                next_id += 1;
            }
            // Queue ENTERS per token in stamp order -- mirrors the
            // sister `CreateToken` arm's pending dispatch shape. The
            // token enters tapped but its ETB still fires (CR 603.6e
            // -- entering tapped does not suppress the enters trigger).
            state.pending_etb_dispatches.extend(token_ids);
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
        // **Basic-land filter: `card_types contains "Land"` AND
        // `supertypes contains "Basic"`.** Mirrors Python's
        // `is_basic_land` = `is_land and "Basic" in supertypes` exactly
        // (CR 205.4a — a basic land is a land with the Basic supertype).
        // Round-30 supertypes substrate (`feature/rust-supertypes-
        // registry` merge `ef8fa004`) added `CardPrinting.supertypes:
        // Vec<String>` with JSON load + getter; the round-22 sibling
        // `Effect::SearchLibraryForCard` arm flipped its
        // `legendary_creature` predicate to consume it at the same
        // time, but this arm was left on the card_types-only proxy
        // (PARTIAL-RESOLVED in SEARCH_LIMITATIONS entry #15). This
        // slice closes that residue: predicate now reads
        // `card_types Land AND supertypes Basic`, matching Python's
        // `is_basic_land` bit-for-bit. Pre-migration the proxy was
        // faithful for the EoE pool (every basic land carried
        // card_types=["Land"] with no non-basic land sharing this
        // dispatch path), so the round-21 regression pins still pass —
        // this is a code-cleanup migration that hardens the predicate
        // against future non-basic-land entries on the bridge.
        //
        // **Post-search shuffle (CR 701.19 / 701.22 — G19 closure).**
        // After all `count` basic-land picks (or partial-fill on
        // early exhaust), the library is Fisher-Yates shuffled in
        // place. Mirrors the post-CE8 `fisher_yates_shuffle_optional`
        // primitive in `state_ops_library.rs` (and its 7 sibling
        // shuffle sites) — same xorshift64 control flow, just
        // inlined here per the per-slice file-isolation convention
        // every other arm in this file follows.
        //
        // **Seed source — `state.rng_ref()` external rng if set,
        // xorshift64 fallback otherwise (Effect-rng-threading closure,
        // G19 follow-up).** CE8 Slice 2 wired all 8 pymethod-surface
        // shuffle sites to consume an optional `rng: &Bound<PyAny>`
        // kwarg, falling through to xorshift64 when `None`. The
        // Effect-rng-threading closure extends that substrate to the
        // single Effect arm that consumes randomness today
        // (`Effect::SearchLibraryForBasicLandTapped`) by stashing the
        // optional `random.Random` on `GameState.rng` (caller-set via
        // `set_external_rng`) rather than threading a parameter
        // through every intervening call site
        // (`apply_effect` / `resolve_top_of_stack` / etc — Option A in
        // `docs/RUST_EFFECT_RNG_AUDIT.md`). When `state.rng_ref()` is
        // `Some(py_rng)`, the post-search Fisher-Yates reads draws via
        // `external_rng::next_below(py_rng, n)` → byte-identical to
        // Python's `random.Random.shuffle(list)`. When `None`, the
        // legacy xorshift64 path runs — seed derived deterministically
        // from `(turn_number, active_player, source_obj_id,
        // library_len)`, stable across reruns of the same starting
        // state.
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
        // `controller` field is stamped to the SEARCHER (the
        // source's controller, per I69) — searching for someone
        // else's basic land into their own battlefield isn't a
        // thing in real MTG, so the searched land enters under the
        // searcher's control.
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
            // **Controller resolution (I69 follow-up to the I59 /
            // I60 / I63 / I64 / I65 / I66 / I67 / I68 controller-
            // of-effect substrate).** Prefer the transient
            // `state.current_resolve_source_controller` (set by
            // the stack resolver around each `apply_effect` call),
            // falling back to `state.active_player` for back-compat
            // with direct `apply_effect_pub` callers. Same pattern
            // as `Effect::DrawCards` / `Effect::GainLife` /
            // `Effect::Mill` / `Effect::Sacrifice` — CR 119.5 /
            // 608.2: an effect resolves under its source's
            // controller. For SearchLibraryForBasicLandTapped
            // ("your library"), the searcher is the SOURCE'S
            // controller, not the active player. Mirrors the
            // Python `SearchLibraryForBasicLandTapped.resolve`
            // shape, which takes `controller_id` from the
            // resolver (the StackItem's controller).
            //
            // **Why the fix.** Pre-fix this arm hardcoded
            // `controller_idx = state.active_player`. Wrong when
            // the resolving spell / triggered ability has a
            // controller != active_player. Example: on p0's turn,
            // p1's Cultivate-shape spell ("search your library
            // for up to 2 basic land cards") resolves — pre-fix
            // it pulled basics from P0'S library onto P0's
            // battlefield (the active player), not p1's; post-fix
            // it correctly pulls from p1's library onto p1's
            // battlefield.
            //
            // **xorshift seed unchanged.** The fallback seed at
            // the post-search shuffle still mixes `state.active_-
            // player` (alongside turn, source_obj_id, library_-
            // len). Changing it would break the existing
            // `test_resolve_search_library_for_basic_land_tapped_-
            // shuffle_is_deterministic` pin, and the seed is a
            // pure-state determinism input, not a behavior switch
            // — per-run uniqueness comes from source_obj_id +
            // library_len mixing.
            let controller_idx = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            let controller_u8 = controller_idx as u8;
            // ETB-trigger Slice 2 (RS2): collect the obj_id of every
            // land we move onto the battlefield so we can fan out
            // `dispatch_event(Event::Enters, ...)` for each AFTER the
            // post-search shuffle drops its registry/zone borrows.
            let mut entered_ids: Vec<u32> = Vec::with_capacity(n);
            for _ in 0..n {
                // Locate the topmost basic-land match (forward iter
                // = top-to-bottom post-CE3, lib[0] = top). Inlined
                // here (vs. delegating to the search-only sibling)
                // so we have the Vec INDEX for removal, not just the
                // obj_id.
                let pos: Option<usize> = {
                    let lib = &state.players[controller_idx].library;
                    let mut found: Option<usize> = None;
                    for (i, obj) in lib.iter().enumerate() {
                        let printing = match state.registry.lookup(obj.printing_id) {
                            Some(p) => p,
                            None => continue,
                        };
                        // Round-37 supertypes-substrate migration:
                        // basic-land predicate is `card_types Land AND
                        // supertypes Basic` (CR 205.4a), bit-equivalent
                        // to Python's `is_basic_land`. Sibling round-22
                        // `Effect::SearchLibraryForCard` arm consumes
                        // the same `printing.supertypes.iter().any(|s|
                        // s == "Basic")` substrate for its
                        // `legendary_creature` predicate.
                        if printing.card_types.iter().any(|t| t == "Land")
                            && printing.supertypes.iter().any(|s| s == "Basic")
                        {
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
                // CE4 closure: reserve before the player-mut borrow.
                let etb_ts = crate::state::reserve_etb_timestamp(state);
                let player = &mut state.players[controller_idx];
                let lib = Arc::make_mut(&mut player.library);
                let mut obj = lib.remove(p);
                // Stamp battlefield entry: tapped, not summoning-sick
                // (CR 302.1 applies to creatures; lands don't have
                // summoning sickness regardless). Controller = the
                // SEARCHER (source's controller, per I69).
                obj.zone = ZONE_BATTLEFIELD;
                obj.tapped = true;
                obj.summoning_sick = false;
                obj.controller = controller_u8;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                obj.etb_timestamp = etb_ts;
                entered_ids.push(obj.id);
                Arc::make_mut(&mut player.battlefield).push(obj);
            }
            // G19 closure: CR 701.19 / 701.22 — always shuffle the
            // library after a search, whether or not a card was
            // found (the early-`break` above on no-match falls
            // through to here too). Effect-rng-threading closure:
            // route through `state.rng_ref()` when set (external
            // Python `random.Random`), fall back to inlined
            // xorshift64 otherwise; seed mixes turn / active_player /
            // source_obj_id / library_len for determinism within a
            // run without giving identical permutations across
            // separate searches in the same game.
            let lib_len = state.players[controller_idx].library.len();
            if lib_len >= 2 {
                // Effect-rng path: consume from the stashed Python
                // `random.Random` if the caller installed one via
                // `set_external_rng`. We extract the `Py<PyAny>` into
                // an owned reference BEFORE taking the `&mut
                // self.players[..]` borrow so the rng borrow doesn't
                // conflict with the mutable-zone borrow that
                // `Arc::make_mut` produces below.
                let py_rng_owned: Option<Py<PyAny>> = state
                    .rng_ref()
                    .map(|r| Python::with_gil(|py| r.clone_ref(py)));
                if let Some(py_rng) = py_rng_owned {
                    let player = &mut state.players[controller_idx];
                    let lib = Arc::make_mut(&mut player.library);
                    let n = lib.len();
                    Python::with_gil(|py| -> PyResult<()> {
                        let bound = py_rng.bind(py);
                        for i in (1..n).rev() {
                            let j = crate::external_rng::next_below(bound, i + 1)?;
                            lib.swap(i, j);
                        }
                        Ok(())
                    })?;
                } else {
                    // xorshift64 fallback: distinct seed per (turn,
                    // ap, source, lib_len) tuple. The zero-collapse
                    // defense matches every other xorshift site in
                    // the engine.
                    let mut seed = (state.turn_number as u64)
                        .wrapping_mul(0x9E37_79B9_7F4A_7C15)
                        ^ ((state.active_player as u64) << 56)
                        ^ ((source_obj_id as u64) << 16)
                        ^ (lib_len as u64);
                    if seed == 0 {
                        seed = 0xdead_beef_dead_beef;
                    }
                    let player = &mut state.players[controller_idx];
                    let lib = Arc::make_mut(&mut player.library);
                    let n = lib.len();
                    let mut x = seed;
                    for i in (1..n).rev() {
                        // xorshift64 step.
                        x ^= x << 13;
                        x ^= x >> 7;
                        x ^= x << 17;
                        // Rejection-sample to an unbiased index in
                        // [0, i+1). i+1 <= library size (~100), so the
                        // rejection-rate cost is negligible.
                        let n_u64 = (i + 1) as u64;
                        let bound = u64::MAX - (u64::MAX % n_u64);
                        let mut r = x;
                        while r >= bound {
                            r ^= r << 13;
                            r ^= r >> 7;
                            r ^= r << 17;
                            x = r;
                        }
                        let j = (r % n_u64) as usize;
                        lib.swap(i, j);
                    }
                }
            }
            // ETB-trigger Slice 2 (RS2): queue ENTERS dispatches per
            // searched-up land, in stamp order (= the order they were
            // moved onto the battlefield above). The caller
            // (`resolve_top_of_stack` / `_pause`) drains the queue
            // after popping the resolving spell's stack item.
            state.pending_etb_dispatches.extend(entered_ids);
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
            // I61: prefer the transient source-controller swap (same
            // pattern as I59 / I60 reader-side fix).
            let controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
            let pidx = controller as usize;
            // Clamp count to library size (CR 701.43 fold).
            let lib_len = state.players[pidx].library.len();
            let n = (*count as usize).min(lib_len);
            // Remove n cards off library TOP. Post-CE3 zones
            // convention: top of library = lib[0]. So we remove from
            // the head n times. Order in `cards`: cards[0] is the
            // topmost card (first removed), cards[1] is second-from-
            // top, etc. The submit dispatcher preserves this ordering
            // when routing back to the library top.
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(n);
            for _ in 0..n {
                // Always remove index 0 — the new top after each
                // prior remove shifts down.
                let removed = lib_mut.remove(0);
                cards.push(removed);
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
        //
        // **Controller resolution (I82 follow-up to the
        // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 / I69 /
        // I70 / I71 / I72 / I73 / I74 / I75 / I76 / I77 / I78 /
        // I79 / I80 / I81 controller-of-effect substrate).**
        // "Your graveyard" in oracle text means the source-
        // controller's graveyard, NOT the active player's
        // graveyard. CR 119.5 / 608.2 — an effect resolves under
        // its source's controller; "your" pronouns in oracle text
        // are bound to that controller, not to whichever player
        // happens to have priority at resolve time.
        //
        // **Why the fix.** Pre-fix this arm computed
        // `controller_idx = state.active_player as usize`, used
        // for both the source graveyard scan AND the destination
        // hand push. Wrong when the resolving spell / triggered
        // ability has a controller != active_player. Example:
        // on p0's turn, p1 casts a Bone-Plate-Skeleton-shape
        // instant — pre-fix it scanned p0's graveyard for a
        // creature and returned that creature to p0's hand
        // (active_player=0); post-fix it correctly scans p1's
        // graveyard and returns the creature to p1's hand.
        // Mirrors Python's
        // `ReturnFromGraveyard.resolve(state, controller_id, targets)`
        // at `effects/generic/graveyard.py:195` and its
        // `_move_one(state, controller_id, card)` helper, which
        // both pin the "your graveyard"/"your hand" zones to
        // `state.player_by_id(controller_id)`.
        //
        // Sibling closure to I81 (CreateToken — positive-
        // controller arm). Same transient-slot lookup preamble.
        Effect::ReturnCreatureFromYourGraveyardToHand => {
            let _ = source_obj_id;
            let controller_idx = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player) as usize;
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
        // **Phase 5 rider-widened return-to-hand: artifact-or-
        // creature variant.** Mirrors the bare unit-variant arm
        // above exactly, with one filter delta: the disjunction
        // `Creature OR Artifact` (vs the unit variant's
        // `Creature` only).
        //
        // **Controller-of-effect.** Inherits the I82 contract:
        // `controller_idx` derives from
        // `current_resolve_source_controller`, falling back to
        // `active_player` for direct apply_effect_pub callers. The
        // graveyard scan and hand push both anchor to the source's
        // controller — cross-controller routing (p1's ETB resolving
        // on p0's turn) Just Works.
        //
        // **Disjunction shape.** The legal-target filter widens
        // from `card_types.contains("Creature")` to
        // `card_types.contains("Creature") ||
        //  card_types.contains("Artifact")`. Artifact-creatures
        // (printings carrying BOTH types) match at the first
        // branch and are pulled.
        //
        // **Real EoE consumer.** Interceptor Mechan (EoE):
        // "When this creature enters, return target artifact or
        // creature card from your graveyard to your hand."
        Effect::ReturnArtifactOrCreatureFromYourGraveyardToHand => {
            let _ = source_obj_id;
            let controller_idx = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player) as usize;
            let target_obj_id: Option<u32> = state.players[controller_idx]
                .graveyard
                .iter()
                .find_map(|obj| match state.registry.lookup(obj.printing_id) {
                    Some(printing)
                        if printing.card_types.iter().any(|t| t == "Creature")
                            || printing
                                .card_types
                                .iter()
                                .any(|t| t == "Artifact") =>
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
        // **Phase 5 rider-widened return-to-hand: creature-or-
        // Spacecraft variant.** Sibling to the artifact-or-
        // creature arm. Filter delta: the disjunction is
        // `Creature OR subtype Spacecraft` — Spacecraft is a
        // SUBTYPE (artifact subtype), not a card type, so the
        // second branch reads `printing.subtypes`, not
        // `printing.card_types`. Mirrors Python's
        // `printing.is_spacecraft` which reads
        // `"Spacecraft" in subtypes` off the Subtypes substrate.
        //
        // **Effective-subtypes scope.** Same caveat as the other
        // subtype-reading sites in the Rust codebase (see
        // `subject_has_subtype` at cards.rs:2141): reads the
        // static `printing.subtypes` directly. No effective_-
        // subtypes layer (CR 613 layer 4) — type-modifying
        // continuous effects that would grant "Spacecraft" to
        // a non-Spacecraft printing aren't observable here. In
        // the EoE pool, the cards a player would want to recur
        // are PRINTED Spacecraft, so the static read is correct
        // for the consumer set.
        //
        // **Real EoE consumer.** Fell Gravship (EoE) suffix:
        // "...then return a creature or Spacecraft card from
        // your graveyard to your hand." (The leading mill-3 is
        // composed elsewhere in the trigger's effect sequence;
        // this arm is the leaf return-effect substrate.)
        Effect::ReturnCreatureOrSpacecraftFromYourGraveyardToHand => {
            let _ = source_obj_id;
            let controller_idx = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player) as usize;
            let target_obj_id: Option<u32> = state.players[controller_idx]
                .graveyard
                .iter()
                .find_map(|obj| match state.registry.lookup(obj.printing_id) {
                    Some(printing)
                        if printing.card_types.iter().any(|t| t == "Creature")
                            || printing
                                .subtypes
                                .iter()
                                .any(|s| s == "Spacecraft") =>
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
        // **Phase 5 rider-widened return-to-hand: enchantment-or-
        // creature variant.** Sibling to the artifact-or-creature
        // and creature-or-spacecraft arms. Filter delta: the
        // disjunction is `Creature OR Enchantment` — both branches
        // read off `printing.card_types` (Enchantment is a CARD
        // TYPE, not a subtype, so this differs from the Spacecraft
        // arm which reads `printing.subtypes` for the second
        // branch).
        //
        // **Controller-of-effect.** Inherits the I82 contract:
        // `controller_idx` derives from
        // `current_resolve_source_controller`, falling back to
        // `active_player` for direct apply_effect_pub callers. The
        // graveyard scan and hand push both anchor to the source's
        // controller — cross-controller routing (p1's ETB resolving
        // on p0's turn) Just Works.
        //
        // **Disjunction shape.** The legal-target filter widens
        // from `card_types.contains("Creature")` to
        // `card_types.contains("Creature") ||
        //  card_types.contains("Enchantment")`. Enchantment-
        // creatures (printings carrying BOTH types — the EoE
        // pool's "Enchantment Creature — ..." printings) match at
        // the first branch and are pulled.
        //
        // **EoE consumer (audit).** Rescue Skiff (EoE) is the
        // unique EoE source carrying the "creature or enchantment
        // card from your graveyard" rider, but its destination is
        // the BATTLEFIELD, not the hand — Rescue Skiff itself
        // unblocks via the to-battlefield sibling that lands as a
        // separate slice. This to-hand variant is the direct
        // sibling of the existing `or_artifact` / `or_spacecraft`
        // to-hand arms and lands here for substrate symmetry: as
        // soon as a real-EoE consumer of "creature or enchantment
        // card from your graveyard to your hand" appears in a
        // future set on the audit, the bridge is already in place.
        Effect::ReturnEnchantmentOrCreatureFromYourGraveyardToHand => {
            let _ = source_obj_id;
            let controller_idx = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player) as usize;
            let target_obj_id: Option<u32> = state.players[controller_idx]
                .graveyard
                .iter()
                .find_map(|obj| match state.registry.lookup(obj.printing_id) {
                    Some(printing)
                        if printing.card_types.iter().any(|t| t == "Creature")
                            || printing
                                .card_types
                                .iter()
                                .any(|t| t == "Enchantment") =>
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
        // **Controller resolution (I83 follow-up to the
        // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 / I69 /
        // I70 / I71 / I72 / I73 / I74 / I75 / I76 / I77 / I78 /
        // I79 / I80 / I81 / I82 controller-of-effect substrate).**
        // Sibling closure to I82 (ReturnCreatureFromYourGraveyard-
        // ToHand) — same "your graveyard" reanimation shape;
        // differs only in destination zone (battlefield vs hand).
        // "Your" pronouns bind to the source's controller, not
        // the active player. CR 119.5 / 608.2.
        //
        // **Why the fix.** Pre-fix this arm computed
        // `controller_idx = state.active_player as usize`, used
        // for the source graveyard scan, the post-find Vec
        // position re-scan, the planeswalker starting-loyalty
        // pre-read, the graveyard-pop, AND the destination
        // battlefield push. Wrong when the resolving spell /
        // triggered ability has a controller != active_player.
        // Example: on p0's turn, p1 casts a Zombify-shape
        // sorcery — pre-fix it scanned p0's graveyard for a
        // creature and reanimated it on p0's battlefield under
        // p0's control (active_player=0); post-fix it correctly
        // scans p1's graveyard and reanimates on p1's battlefield
        // under p1's control. Mirrors Python's
        // `ReturnFromGraveyard.resolve(state, controller_id,
        // targets)` at `effects/generic/graveyard.py:195` and
        // its `_move_one(state, controller_id, card)` helper,
        // which both pin "your graveyard"/"your battlefield"
        // zones to `state.player_by_id(controller_id)`. The
        // reanimated permanent's GameObject.controller field
        // (preserved as the existing obj.controller from the
        // pre-pop state) is left unchanged by this fix — the
        // CR-correct semantics here are that the reanimated
        // permanent enters under the reanimation effect's
        // controller, which is what the post-fix
        // controller_idx now correctly resolves to.
        //
        // Same transient-slot lookup preamble as I59-I82; the
        // controller_idx value cascades into all five readers
        // (scan, position re-scan, walker pre-read, graveyard-
        // pop, bf-push). The ETB-trigger dispatch
        // (`pending_etb_dispatches`) sees the reanimated id
        // regardless of recipient bf, so the trigger fan-out
        // shape is unaffected.
        Effect::ReturnCreatureFromYourGraveyardToBattlefield => {
            let _ = source_obj_id; // controller-targeted, not source-relative
            let controller_idx = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player) as usize;
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
            // CE4 closure: reserve ETB timestamp before player-mut borrow.
            let etb_ts = crate::state::reserve_etb_timestamp(state);
            // CE20 Slice 5 (Walker loyalty — starting_loyalty ETB
            // seeding). Pre-read the printing's walker shape on the
            // immutable registry BEFORE the player-mut borrow.
            let starting_loyalty: i32 = {
                let pos_gy = state.players[controller_idx]
                    .graveyard
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id was just found in graveyard");
                let pid = state.players[controller_idx].graveyard[pos_gy].printing_id;
                match state.registry.lookup(pid) {
                    Some(printing)
                        if printing.card_types.iter().any(|t| t == "Planeswalker") =>
                    {
                        printing.starting_loyalty
                    }
                    _ => 0,
                }
            };
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
            // CE20 Slice 5: walker reanimation — reset loyalty to
            // printed starting value per CR 613.x (the new object is
            // distinct from the previous one and starts fresh).
            obj.loyalty_counters = starting_loyalty;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            obj.etb_timestamp = etb_ts;
            // I83 controller-of-effect fix: stamp the reanimated
            // permanent's `controller` byte with the
            // reanimation-effect's controller. CR 110.2 / 614.x —
            // when an object enters the battlefield from another
            // zone, its controller becomes the player whose effect
            // moved it (or the player who put it there). For the
            // typical "return target creature card from YOUR
            // graveyard" reanimation, that's the source-controller
            // we just resolved. Pre-fix this byte was left as the
            // pre-move value (owner-keyed in graveyard, which
            // happened to match `state.active_player` only when
            // controller == active_player and the original owner
            // was the active player). Post-fix, the new
            // battlefield permanent is correctly controlled by the
            // reanimating effect's controller regardless of where
            // the card came from.
            obj.controller = controller_idx as u8;
            let entered_id = obj.id;
            Arc::make_mut(&mut state.players[controller_idx].battlefield).push(obj);
            // ETB-trigger Slice 2 (RS3): queue ENTERS dispatch for
            // the reanimated creature. Drained by the surrounding
            // resolver after the resolving spell's stack item pops.
            state.pending_etb_dispatches.push(entered_id);
        }
        // **Phase 5 rider-widened return-to-battlefield: enchantment-
        // or-creature variant.** Sibling to the bare to-bf unit
        // variant immediately above. Filter delta: the disjunction
        // is `Creature OR Enchantment` — both branches read off
        // `printing.card_types` (Enchantment is a CARD TYPE, not a
        // subtype). Same first-creature-in-graveyard scan order
        // (front = oldest by push), same I83 controller-of-effect
        // contract (`controller_idx` from
        // `current_resolve_source_controller`, fallback to
        // `active_player`), same CR 400.7 zone-change reset, same
        // ETB-trigger fan-out via `pending_etb_dispatches`.
        //
        // **EoE consumer.** Rescue Skiff (EoE): "When this Spacecraft
        // enters, return target creature or enchantment card from
        // your graveyard to the battlefield." Unlike the to-hand
        // sibling variant which has no real-EoE consumer (Rescue
        // Skiff is to-bf, not to-hand), THIS arm is the direct
        // unblocker for Rescue Skiff itself.
        //
        // **Disjunction shape.** The legal-target filter widens
        // from `card_types.contains("Creature")` to
        // `card_types.contains("Creature") ||
        //  card_types.contains("Enchantment")`. Enchantment-
        // creatures (printings carrying BOTH types — the EoE
        // pool's "Enchantment Creature — ..." printings) match at
        // the first branch and are pulled.
        //
        // **Walker reseed (CE20 Slice 5).** Same pre-read of
        // `starting_loyalty` on the registry BEFORE the player-mut
        // borrow as the bare to-bf arm; reseeds `loyalty_counters`
        // on the reanimated permanent. Real practice: an
        // Enchantment-Planeswalker would be admitted by both
        // branches of the disjunction (Creature primary or
        // Enchantment widening); the walker reseed correctly fires.
        //
        // **I83 controller stamp.** The reanimated permanent's
        // `controller` byte stamps to `controller_idx` (the
        // reanimation-effect's controller per CR 110.2 / 614.x),
        // mirroring the bare to-bf arm. On p0's turn, p1's Rescue-
        // Skiff ETB scans p1's graveyard, reanimates onto p1's
        // battlefield, and the new permanent is correctly p1-
        // controlled.
        Effect::ReturnEnchantmentOrCreatureFromYourGraveyardToBattlefield => {
            let _ = source_obj_id; // controller-targeted, not source-relative
            let controller_idx = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player) as usize;
            // Find first creature OR enchantment in controller's
            // graveyard (front = smallest Vec index = top of the
            // iteration order). Drop registry borrow before mutating.
            let target_obj_id: Option<u32> = state.players[controller_idx]
                .graveyard
                .iter()
                .find_map(|obj| match state.registry.lookup(obj.printing_id) {
                    Some(printing)
                        if printing.card_types.iter().any(|t| t == "Creature")
                            || printing
                                .card_types
                                .iter()
                                .any(|t| t == "Enchantment") =>
                    {
                        Some(obj.id)
                    }
                    _ => None,
                });
            let Some(target_id) = target_obj_id else {
                return Ok(()); // empty / no-match: silent fizzle
            };
            // CE4 closure: reserve ETB timestamp before player-mut borrow.
            let etb_ts = crate::state::reserve_etb_timestamp(state);
            // CE20 Slice 5 (Walker loyalty — starting_loyalty ETB
            // seeding). Pre-read the printing's walker shape on the
            // immutable registry BEFORE the player-mut borrow.
            let starting_loyalty: i32 = {
                let pos_gy = state.players[controller_idx]
                    .graveyard
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id was just found in graveyard");
                let pid = state.players[controller_idx].graveyard[pos_gy].printing_id;
                match state.registry.lookup(pid) {
                    Some(printing)
                        if printing.card_types.iter().any(|t| t == "Planeswalker") =>
                    {
                        printing.starting_loyalty
                    }
                    _ => 0,
                }
            };
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
            obj.loyalty_counters = starting_loyalty;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            obj.etb_timestamp = etb_ts;
            // I83 controller-of-effect stamp: reanimated permanent's
            // `controller` byte = the reanimation-effect's controller
            // (CR 110.2 / 614.x). Mirrors the bare to-bf arm.
            obj.controller = controller_idx as u8;
            let entered_id = obj.id;
            Arc::make_mut(&mut state.players[controller_idx].battlefield).push(obj);
            // ETB-trigger fan-out: queue ENTERS dispatch for the
            // reanimated permanent. Drained by the surrounding
            // resolver after the resolving spell's stack item pops.
            state.pending_etb_dispatches.push(entered_id);
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
        // BLOCKED-RUST-EFFECT slice (round 44) -- each opponent of the
        // source-controller loses life equal to the source-controller's
        // artifact count. Sister of round-26's
        // `Effect::EachOpponentLosesLife { amount }` (same recipient set
        // + apply step) and round-32's
        // `DealDamageToOpponentCreatureByArtifactCount` / round-34's
        // `SurveilXEqualToArtifactCount` (same artifact-count
        // denominator). FIFTH apply substrate to pick up the X-from-
        // count plumbing established by round-32 (damage), round-33
        // (counters), round-34 (surveil), round-42 (mill).
        //
        // **Direct life subtraction (CR 118.4) -- NOT damage.** Mirrors
        // round-26 EachOpponentLosesLife exactly: routes around damage-
        // prevention / Worship-style replacement effects (CR 614).
        // Two-player engine: 2-player "each opponent" reduces to "the
        // one opponent" at `1 - controller`.
        //
        // **Artifact denominator.** Walk the source-controller's bf
        // once; for each obj count +1 if `printing.card_types` contains
        // "Artifact". BIT-FOR-BIT mirror of the round-32 / round-34
        // artifact-count walking pattern -- same scan, same predicate,
        // same `saturating_add` overflow guard. Lands that are also
        // artifacts count, tokens like Lander count. Dual-typed
        // artifact-creatures count for BOTH the artifact-count and the
        // creatures-controlled denominators independently. The source
        // itself counts toward the denominator if it is an Artifact
        // still on the bf at resolve time (mirrors Python's vanilla
        // walk over `state.battlefield` -- no source-exclusion clause).
        //
        // **Source-finder dispatch (round-26 / round-32 sister
        // pattern).** 5-zone walk + stack scan. Source not found
        // anywhere = silent fizzle (lost-track-of-source tolerance,
        // mirrors EachOpponentLosesLife / DiscardSelf shape).
        //
        // **Zero-count = silent no-op** (matches Python's `if
        // artifact_count <= 0: return` short-circuit before the
        // per-opponent loop; also mirrors GainLife / DrawCards / Mill /
        // EachOpponentLosesLife / DiscardSelf zero-amount conventions).
        Effect::EachOpponentLosesLifeEqualToArtifactCount => {
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors round-26 EachOpponentLosesLife sister shape
            // exactly).
            let mut source_controller: Option<u8> = None;
            'outer_sc_eollac: for player in state.players.iter() {
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
                            break 'outer_sc_eollac;
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
            // Count source-controller's artifacts on bf. Mirrors
            // Python's `sum(1 for o in state.battlefield if
            // o.controller_id == controller_id and o.printing.is_artifact)`
            // shape. Walks the round-32 artifact-count loop
            // BIT-FOR-BIT.
            let cidx = controller as usize;
            let mut amount: i32 = 0;
            for obj in state.players[cidx].battlefield.iter() {
                let Some(printing) = state.registry.printings.get(obj.printing_id as usize)
                else {
                    continue;
                };
                if printing.card_types.iter().any(|t| t == "Artifact") {
                    amount = amount.saturating_add(1);
                }
            }
            if amount <= 0 {
                return Ok(()); // no artifacts → silent no-op (matches Python's `if artifact_count <= 0: return`)
            }
            // Each opponent: the OTHER player in 2-player land.
            let opponent_id = 1 - controller;
            let opponent_idx = opponent_id as usize;
            // Direct life subtraction -- not damage. Negative life is
            // handled by SBA loop. Mirrors round-26 sister BIT-FOR-BIT.
            state.players[opponent_idx].life =
                state.players[opponent_idx].life.saturating_sub(amount);
        }
        // BLOCKED-RUST-EFFECT slice (round 48) -- each opponent of the
        // source-controller loses life equal to the source-controller's
        // CURRENT LIFE TOTAL. Sister of round-44's
        // `Effect::EachOpponentLosesLifeEqualToArtifactCount` (SAME
        // recipient set + apply step + apply substrate) and round-42's
        // `MillTargetPlayerEqualToYourLifeTotal` / round-47's
        // `DealDamageToOpponentCreatureByLifeTotal` (SAME life-total
        // denominator on OTHER substrates). SECOND denominator on the
        // life-loss-each-opponent apply substrate; walks the
        // X-from-count matrix to a third (substrate, life-total) cell.
        //
        // **Direct life subtraction (CR 118.4) -- NOT damage.** Mirrors
        // round-44 EachOpponentLosesLifeEqualToArtifactCount exactly:
        // routes around damage-prevention / Worship-style replacement
        // effects (CR 614). Two-player engine: "each opponent" reduces
        // to "the one opponent" at `1 - controller`.
        //
        // **Life-total denominator.** Read the source-controller's
        // current life total and clamp negative life to 0
        // (`life.max(0)`) -- BIT-FOR-BIT mirror of the round-42
        // `MillTargetPlayerEqualToYourLifeTotal` life clamp and Python's
        // `max(0, life)` shape. The round-44 sister walks the bf for an
        // artifact count; this arm reads the life total instead -- the
        // ONLY mechanical difference between the two arms (same source-
        // finder, same apply, same zero-no-op).
        //
        // **Source-finder dispatch (round-44 sister pattern).** 5-zone
        // walk + stack scan. Source not found anywhere = silent fizzle
        // (lost-track-of-source tolerance, mirrors
        // EachOpponentLosesLife / EachOpponentLosesLifeEqualToArtifactCount
        // / DiscardSelf shape). Uses the 5-zone walk rather than
        // `current_resolve_source_controller` for cross-arm consistency
        // with the round-44 sister and so the inject-and-fire-ENTERS
        // synthetic harness resolves correctly.
        //
        // **Zero-life = silent no-op** (matches Python's `if amount <=
        // 0: return` short-circuit before the per-opponent loop; also
        // mirrors GainLife / DrawCards / Mill / EachOpponentLosesLife /
        // EachOpponentLosesLifeEqualToArtifactCount / DiscardSelf
        // zero-amount conventions).
        Effect::EachOpponentLosesLifeEqualToYourLifeTotal => {
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors round-44 EachOpponentLosesLifeEqualToArtifactCount
            // sister shape exactly).
            let mut source_controller: Option<u8> = None;
            'outer_sc_eollyl: for player in state.players.iter() {
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
                            break 'outer_sc_eollyl;
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
            // Life-total denominator: clamp negative life to 0
            // (matches Python's `max(0, life)` clamp and the round-42
            // MillTargetPlayerEqualToYourLifeTotal precedent).
            let cidx = controller as usize;
            let amount: i32 = state.players[cidx].life.max(0);
            if amount <= 0 {
                return Ok(()); // life <= 0 -> silent no-op
            }
            // Each opponent: the OTHER player in 2-player land.
            let opponent_id = 1 - controller;
            let opponent_idx = opponent_id as usize;
            // Direct life subtraction -- not damage. Negative life is
            // handled by SBA loop. Mirrors round-44 sister BIT-FOR-BIT.
            state.players[opponent_idx].life =
                state.players[opponent_idx].life.saturating_sub(amount);
        }
        // BLOCKED-RUST-EFFECT slice (round 45) -- the source's
        // controller GAINS life equal to the source-controller's
        // artifact count. Sister of round-26's `Effect::GainLife
        // { amount }` (same recipient = controller-self + same apply
        // step) and round-32's
        // `DealDamageToOpponentCreatureByArtifactCount` / round-34's
        // `SurveilXEqualToArtifactCount` / round-44's
        // `EachOpponentLosesLifeEqualToArtifactCount` (same
        // artifact-count denominator). SIXTH apply substrate to pick
        // up the X-from-count plumbing established by round-32
        // (damage), round-33 (counters), round-34 (surveil), round-42
        // (mill), round-44 (life-loss-each-opponent). Controller-self
        // mirror of round-44: same denominator, inverted recipient
        // (controller-self vs opponents-of-controller) AND inverted
        // sign (gain vs loss).
        //
        // **Direct life addition (CR 119.3) -- NOT damage healing.**
        // Mirrors round-26 GainLife exactly: simple `+=` (not
        // `saturating_add`, matching the round-26 sister bit-for-bit;
        // life total is i32 so realistic gain values won't overflow).
        // Routes around damage-prevention hooks (CR 119 distinguishes
        // life gain from damage).
        //
        // **Artifact denominator.** Walk the source-controller's bf
        // once; for each obj count +1 if `printing.card_types` contains
        // "Artifact". BIT-FOR-BIT mirror of the round-32 / round-34 /
        // round-44 artifact-count walking pattern -- same scan, same
        // predicate, same `saturating_add` overflow guard. Lands that
        // are also artifacts count, tokens like Lander count. Dual-
        // typed artifact-creatures count for BOTH the artifact-count
        // and the creatures-controlled denominators independently.
        // The source itself counts toward the denominator if it is an
        // Artifact still on the bf at resolve time (mirrors Python's
        // vanilla walk over `state.battlefield` -- no source-exclusion
        // clause).
        //
        // **Source-finder dispatch (round-26 / round-32 / round-44
        // sister pattern).** 5-zone walk + stack scan. Source not
        // found anywhere = silent fizzle (lost-track-of-source
        // tolerance, mirrors EachOpponentLosesLife / DiscardSelf
        // shape).
        //
        // **Zero-count = silent no-op** (matches Python's `if
        // artifact_count <= 0: return` short-circuit before the
        // life-add; also mirrors GainLife / DrawCards / Mill /
        // EachOpponentLosesLife / DiscardSelf zero-amount conventions).
        //
        // **Why not lean on `current_resolve_source_controller` like
        // bare GainLife.** Bare `Effect::GainLife { amount }` uses
        // the resolve-harness-set `current_resolve_source_controller`
        // shortcut because its denominator is a static field; the
        // dynamic-X arm needs the 5-zone walk because the count must
        // be derived from the source's ACTUAL controller's bf even
        // when the resolve harness's shortcut isn't set (e.g. inject-
        // and-fire-ENTERS synthetic harnesses, plus consistency with
        // the round-44 sister source-finder).
        Effect::GainLifeEqualToArtifactCount => {
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors round-26 EachOpponentLosesLife sister and
            // round-44 EachOpponentLosesLifeEqualToArtifactCount sister
            // shape exactly).
            let mut source_controller: Option<u8> = None;
            'outer_sc_glac: for player in state.players.iter() {
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
                            break 'outer_sc_glac;
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
            // Count source-controller's artifacts on bf. Mirrors
            // Python's `sum(1 for o in state.battlefield if
            // o.controller_id == controller_id and o.printing.is_artifact)`
            // shape. Walks the round-32 / round-44 artifact-count loop
            // BIT-FOR-BIT.
            let cidx = controller as usize;
            let mut amount: i32 = 0;
            for obj in state.players[cidx].battlefield.iter() {
                let Some(printing) = state.registry.printings.get(obj.printing_id as usize)
                else {
                    continue;
                };
                if printing.card_types.iter().any(|t| t == "Artifact") {
                    amount = amount.saturating_add(1);
                }
            }
            if amount <= 0 {
                return Ok(()); // no artifacts → silent no-op (matches Python's `if artifact_count <= 0: return`)
            }
            // Direct life addition -- not damage. Mirrors round-26
            // GainLife sister BIT-FOR-BIT (simple `+=`, not
            // saturating_add).
            state.players[cidx].life += amount;
        }
        // BLOCKED-RUST-EFFECT slice (round 49) -- the source's
        // controller GAINS life equal to the source-controller's
        // CURRENT LIFE TOTAL. Sister of round-45's
        // `Effect::GainLifeEqualToArtifactCount` (SAME recipient =
        // controller-self + SAME apply step: direct life addition via
        // `+=`, mirrors round-26 GainLife bit-for-bit, AND the SAME
        // apply substrate: gain-life-controller-self), only the
        // DENOMINATOR read differs (source-controller's current life
        // total instead of their artifact-count walk). SECOND
        // denominator on the gain-life-controller-self apply substrate
        // (artifact-count round-45 -> life-total round-49). Life-total
        // denominator established by round-42's
        // `MillTargetPlayerEqualToYourLifeTotal` (mill), round-47's
        // `DealDamageToOpponentCreatureByLifeTotal` (damage), round-48's
        // `EachOpponentLosesLifeEqualToYourLifeTotal` (life-loss-each-
        // opponent) on OTHER substrates -- this walks the X-from-count
        // matrix to a FOURTH (substrate, life-total) cell.
        //
        // **Life-total clamp.** Clamp negative life to 0 (`life.max(0)`)
        // before use as the denominator -- matches Python's
        // `max(0, life)` and the round-42 / round-47 / round-48
        // life-total clamping precedent (a negative life total can
        // transiently arise from a prior loss/damage in the same
        // resolution window before the SBA loop runs; a negative
        // denominator would be nonsensical). Zero clamped life ->
        // silent no-op (matches Python's `if amount <= 0: return`
        // short-circuit before the life-add; also mirrors GainLife /
        // DrawCards / Mill / EachOpponentLosesLife /
        // GainLifeEqualToArtifactCount / DiscardSelf zero-amount
        // conventions).
        //
        // **Source-finder dispatch (round-45 sister pattern).** 5-zone
        // walk + stack scan. Source not found anywhere = silent fizzle
        // (lost-track-of-source tolerance, mirrors
        // GainLifeEqualToArtifactCount / EachOpponentLosesLife /
        // DiscardSelf shape). The dynamic-X arm needs the 5-zone walk
        // (not the `current_resolve_source_controller` shortcut bare
        // GainLife uses) because the life-total denominator must read
        // from the source's ACTUAL controller even when the resolve
        // harness's shortcut isn't set (e.g. inject-and-fire-ENTERS
        // synthetic harnesses, plus consistency with the round-45/48
        // sister source-finders).
        Effect::GainLifeEqualToYourLifeTotal => {
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors round-45 GainLifeEqualToArtifactCount sister and
            // round-48 EachOpponentLosesLifeEqualToYourLifeTotal sister
            // shape exactly).
            let mut source_controller: Option<u8> = None;
            'outer_sc_glyl: for player in state.players.iter() {
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
                            break 'outer_sc_glyl;
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
            // Life-total denominator: clamp negative life to 0
            // (matches Python's `max(0, life)` clamp and the round-42
            // mill / round-47 damage / round-48 each-opponent-loses
            // life-total clamping precedent).
            let cidx = controller as usize;
            let amount: i32 = state.players[cidx].life.max(0);
            if amount <= 0 {
                return Ok(()); // life <= 0 -> silent no-op
            }
            // Direct life addition -- not damage. Mirrors round-45
            // GainLifeEqualToArtifactCount sister BIT-FOR-BIT (simple
            // `+=`, not saturating_add), only the amount source differs.
            state.players[cidx].life += amount;
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
        // **bf-ETB iteration (I33 closure).** The victim-collection
        // walk uses the shared `crate::bf_iter::bf_iter_etb_sorted`
        // helper so destroyable creatures are enumerated in Python's
        // centralized `state.battlefield` (ETB-monotone) order rather
        // than p0-then-p1 per-player order. Outcome is order-invariant:
        // each destroyable creature ends up in its OWN controller's
        // graveyard regardless of visit order, and per-controller
        // graveyard insertion order is preserved (Python's centralized
        // walk filtered to a single controller produces the same
        // per-controller sequence as the per-player walk did). The
        // change is pre-emptive: visit order becomes load-bearing for
        // future death-trigger emission (CE8 substrate). See I33 in
        // `docs/RUST_PARITY_GAPS.md`.
        Effect::DestroyAllCreatures => {
            let _ = source_obj_id; // implicit-target AOE; source not relevant
            // Collect (controller_idx, obj_id) for every destroyable
            // Creature on either bf in bf-ETB-timestamp order, then
            // pop from each controller's bf and push into their
            // graveyard.
            let destroyable: Vec<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
                .into_iter()
                .filter_map(|obj| {
                    let printing = state.registry.lookup(obj.printing_id)?;
                    if !printing.card_types.iter().any(|t| t == "Creature") {
                        return None;
                    }
                    if printing.keywords.iter().any(|k| k == "indestructible") {
                        return None;
                    }
                    Some((obj.controller as usize, obj.id))
                })
                .collect();
            for (pidx, target_id) in destroyable {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                let pos = match bf_mut.iter().position(|o| o.id == target_id) {
                    Some(p) => p,
                    None => continue, // defensively skip — should never miss
                };
                let mut obj = bf_mut.remove(pos);
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                // CE13 closure: `summoning_sick` is NOT reset here.
                // Python's `turn.move_off_battlefield` deliberately
                // omits the clear (CR 302.1 — sickness is battlefield-
                // only state). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let leaving_printing_id = obj.printing_id;
                let leaving_obj_id = obj.id;
                Arc::make_mut(&mut state.players[pidx].graveyard).push(obj);
                // Slice 11 (DestroyAllCreatures LTB residual). Mirror
                // the 13 single-target Effect-arm bf-exit sites wired
                // by ETB Slice 10: route the void-flag stamping
                // through `mark_left_battlefield_if_nonland` (so the
                // CE13 / I29 invariant lands the same way on the
                // mass-destroy path as on every single-target destroy)
                // AND push the leaving id onto pending_leaves_dispatches
                // so LTB triggers fire on a Wrath. Pre-Slice-11 this
                // arm directly set `permanent_left_battlefield_this_turn`
                // and queued NO LTB triggers — silent on a mass
                // destroy, the 14th LTB-silent site documented in
                // ETB Slice 10's report.
                //
                // **Ordering**: the per-victim drain is deferred to
                // `resolve_top_of_stack`'s
                // `drain_pending_leaves_dispatches` call AFTER the
                // resolving spell's stack pop. Mirrors the Slice 10
                // defer-past-pop pattern — draining inline here would
                // push LTB triggers ABOVE the still-present resolving
                // spell and the subsequent stack.pop() would pop the
                // wrong slot. The queue's natural FIFO + LIFO stack-
                // resolve order land LTB triggers in
                // bf-ETB-timestamp-collection order (oldest victim's
                // LTB resolves LAST since LIFO stack pops most-recent-
                // pushed first).
                mark_left_battlefield_if_nonland(state, leaving_printing_id);
                state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
            }
        }
        // DestroyTargetNonlandPermanent. CR 701.7 with non-land filter
        // — Drag to the Roots / Drill Too Deep pattern. Walks BOTH
        // players' battlefield in ETB-timestamp order via the shared
        // `crate::bf_iter::bf_iter_etb_sorted` helper, picking the
        // first non-Land, non-indestructible permanent. Mirrors
        // Python's `effects/generic/destroy.py:DestroyTargetNonlandPermanent`
        // `TargetSpec(~IsLand() & ~IsPlayer())` filter against the
        // centralized `state.battlefield` walk (no controller
        // restriction). See invariant I39.
        Effect::DestroyTargetNonlandPermanent => {
            let target: Option<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
                .into_iter()
                .find_map(|obj| {
                    let printing = state.registry.lookup(obj.printing_id)?;
                    if printing.card_types.iter().any(|t| t == "Land") {
                        return None;
                    }
                    if printing.keywords.iter().any(|k| k == "indestructible") {
                        return None;
                    }
                    Some((obj.controller as usize, obj.id))
                });
            if let Some((pidx, target_id)) = target {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id from scan but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                // CE13 closure: `summoning_sick` is NOT reset here.
                // Python's `turn.move_off_battlefield` deliberately
                // omits the clear (CR 302.1 — sickness is battlefield-
                // only state). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
                Arc::make_mut(&mut state.players[pidx].graveyard).push(obj);
                // Round-29 Void LTB: nonland target by filter; helper
                // re-checks via printing for defense-in-depth.
                mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
            }
        }
        // DestroyTargetNoncreaturePermanent (round 52). CR 701.7 with a
        // NONCREATURE filter — Extinguisher Battleship ETB head. Walks
        // BOTH players' battlefield in ETB-timestamp order via the
        // shared `crate::bf_iter::bf_iter_etb_sorted` helper, picking
        // the first non-Creature, non-indestructible permanent. Mirrors
        // Python's
        // `effects/generic/destroy.py:DestroyTargetNoncreaturePermanent`
        // `TargetSpec(~IsCreature() & ~IsPlayer())` filter against the
        // centralized `state.battlefield` walk (no controller
        // restriction). Identical dispatch + LTB-fanout shape to the
        // round-24 `DestroyTargetNonlandPermanent` arm above with the
        // filter predicate swapped Land→Creature. Players are
        // structurally excluded (the bf walk only iterates
        // GameObjects). See invariant I39.
        Effect::DestroyTargetNoncreaturePermanent => {
            let target: Option<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
                .into_iter()
                .find_map(|obj| {
                    let printing = state.registry.lookup(obj.printing_id)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        return None;
                    }
                    if printing.keywords.iter().any(|k| k == "indestructible") {
                        return None;
                    }
                    Some((obj.controller as usize, obj.id))
                });
            if let Some((pidx, target_id)) = target {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id from scan but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                // CE13 closure: `summoning_sick` is NOT reset here.
                // Python's `turn.move_off_battlefield` deliberately
                // omits the clear (CR 302.1 — sickness is battlefield-
                // only state). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
                Arc::make_mut(&mut state.players[pidx].graveyard).push(obj);
                // Round-29 Void LTB: helper re-checks via printing for
                // defense-in-depth. (A noncreature destroy never moves
                // a creature off bf, but the helper short-circuits on
                // creature printings anyway — same call as the nonland
                // arm for fan-out symmetry.)
                mark_left_battlefield_if_nonland(state, printing_id);
                // Slice 10: LTB fan-out at the Effect arm — same
                // deferred-drain rationale as the nonland arm above
                // (bf-exit bypasses move_object; queue the leaving id,
                // the drain runs in `resolve_top_of_stack` after the
                // resolving slot pops).
                state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
            }
        }
        // DestroyTargetArtifact. CR 701.7 with Artifact filter — Drill
        // Too Deep / Scour for Scrap pattern. Walks BOTH players'
        // battlefield in ETB-timestamp order via the shared
        // `crate::bf_iter::bf_iter_etb_sorted` helper, picking the
        // first Artifact that is not indestructible. Mirrors
        // Python's `effects/generic/destroy.py:DestroyTargetArtifact`
        // `TargetSpec(IsArtifact())` filter against the centralized
        // `state.battlefield` walk (no controller restriction). See
        // invariant I39.
        Effect::DestroyTargetArtifact => {
            let target: Option<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
                .into_iter()
                .find_map(|obj| {
                    let printing = state.registry.lookup(obj.printing_id)?;
                    if !printing.card_types.iter().any(|t| t == "Artifact") {
                        return None; // not an artifact
                    }
                    if printing.keywords.iter().any(|k| k == "indestructible") {
                        return None;
                    }
                    Some((obj.controller as usize, obj.id))
                });
            if let Some((pidx, target_id)) = target {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id from scan but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                // CE13 closure: `summoning_sick` is NOT reset here.
                // Python's `turn.move_off_battlefield` deliberately
                // omits the clear (CR 302.1 — sickness is battlefield-
                // only state). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
                Arc::make_mut(&mut state.players[pidx].graveyard).push(obj);
                // Round-29 Void LTB: artifact target may also be a
                // land (treasure tokens / artifact lands). Helper gates
                // on the printing.
                mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
            }
        }
        // DestroyTargetArtifactOrTappedCreature (Effect-uncovered
        // Tier-A — Radiant Strike inner half). CR 701.7 with a typed-OR
        // filter: (Artifact) OR (Creature AND tapped). Walks BOTH
        // players' battlefield in ETB-timestamp order via the shared
        // `crate::bf_iter::bf_iter_etb_sorted` helper, picking the
        // first permanent that is either an Artifact OR a tapped
        // Creature and is not indestructible. Mirrors Python's
        // `effects/generic/destroy.py:475
        // DestroyTargetArtifactOrTappedCreature` whose `TargetSpec`
        // filter is `IsArtifact() | (IsCreature() & IsTapped())`,
        // re-verified at resolution per CR 608.2b against the
        // centralized `state.battlefield` walk (no controller
        // restriction). `obj.tapped` is read off the scanned live
        // GameObject — the round-53 effective-state lesson (read where
        // the real card would; the engine has no continuous-effect
        // tap-state layer, so `obj.tapped` IS the effective tapped
        // state both engines agree on). Identical dispatch/LTB-fanout
        // shape to the round-25 `DestroyTargetArtifact` arm above with
        // the predicate widened Artifact → Artifact-OR-tapped-Creature.
        // The `Sequence`+`GainLife` outer shell of Radiant Strike's
        // full effect runs through the already-live `Effect::Sequence`
        // / `Effect::GainLife` arms. See invariant I39.
        Effect::DestroyTargetArtifactOrTappedCreature => {
            let target: Option<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
                .into_iter()
                .find_map(|obj| {
                    let printing = state.registry.lookup(obj.printing_id)?;
                    let is_artifact =
                        printing.card_types.iter().any(|t| t == "Artifact");
                    let is_creature =
                        printing.card_types.iter().any(|t| t == "Creature");
                    // Typed-OR filter: artifact OR (creature AND tapped).
                    // An untapped non-artifact creature is NOT legal
                    // (the OR-filter teeth — pin both engines agree).
                    if !(is_artifact || (is_creature && obj.tapped)) {
                        return None;
                    }
                    if printing.keywords.iter().any(|k| k == "indestructible") {
                        return None;
                    }
                    Some((obj.controller as usize, obj.id))
                });
            if let Some((pidx, target_id)) = target {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id from scan but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                // CE13 closure: `summoning_sick` is NOT reset here.
                // Python's `turn.move_off_battlefield` deliberately
                // omits the clear (CR 302.1 — sickness is battlefield-
                // only state). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
                Arc::make_mut(&mut state.players[pidx].graveyard).push(obj);
                // Round-29 Void LTB: target may be an artifact land or
                // a creature; helper gates on the printing.
                mark_left_battlefield_if_nonland(state, printing_id);
                // R76-2: a "destroy" of a CREATURE is a death (CR
                // 700.4) — its `Event.DIES` triggered abilities MUST
                // fire, exactly as the generic SBA destroy path does
                // (`state_ops_sba.rs`) and as Python's
                // `DestroyTargetArtifactOrTappedCreature.resolve` ->
                // `turn.destroy` -> `move_off_battlefield` does
                // (`_fire_dies_triggers` + the predicate-path
                // `dispatch_event(DIES)` BEFORE
                // `_fire_leaves_battlefield_triggers`). This
                // hand-rolled destroy arm (Radiant Strike's destroy
                // half) previously pushed ONLY
                // `pending_leaves_dispatches`, so a destroyed
                // dies-trigger creature (e.g. Gravpack Monoist ->
                // Robot token) silently never fired its trigger — the
                // round-76 bench-resweep R76-2 divergence (same class
                // as R74-2 `f38df833`, a DIFFERENT Effect arm; that
                // fix added the DIES drain at the 4 resolution sites
                // but did NOT touch this arm). Python (SoT) correct;
                // Rust was wrong. Push order mirrors the SBA path +
                // the `Event::LeavesBattlefield` cards.rs doc-comment
                // contract (DIES first via `pending_dies_dispatches`,
                // LEAVES second via `pending_leaves_dispatches`); the
                // matching resolution-path drain order (DIES drained
                // then LEAVES; LIFO -> LEAVES resolves first)
                // preserves Python's `move_off_battlefield` sequence.
                // Creature-gated like the SBA path / the R74-2
                // DepressurizeEffect fix so a destroyed ARTIFACT (the
                // OR-filter's other leg) does NOT fire a spurious DIES
                // (CR 700.4 — only a creature death fires DIES).
                let victim_is_creature = state
                    .registry
                    .lookup(printing_id)
                    .map(|p| {
                        p.card_types
                            .iter()
                            .any(|t| t == "Creature")
                    })
                    .unwrap_or(false);
                if victim_is_creature {
                    state
                        .pending_dies_dispatches
                        .push(leaving_obj_id);
                }
                // Slice 10: LTB fan-out at the Effect arm — same
                // deferred-drain rationale as the artifact arm above
                // (bf-exit bypasses move_object; queue the leaving id,
                // the drain runs in `resolve_top_of_stack` after the
                // resolving slot pops).
                state.pending_leaves_dispatches.push(leaving_obj_id);
                // Round-55: token-cease sibling of the LEAVES push. The
                // id is queued unconditionally; the is_token gate lives
                // in drain_pending_token_cease (CR 111.7 / 704.5d).
                crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
            }
        }
        // SeedshipImpactEffect (Effect-uncovered Tier-A — Seedship
        // Impact, Lander-rider). CR 701.7 destroy with an
        // Artifact-OR-Enchantment filter + a conditional Lander rider.
        // Mirrors Python's `SeedshipImpactEffect.resolve`
        // (`effects/bespoke.py:1237`): pick the first
        // (Artifact OR "Enchantment" in card_types) permanent; read
        // its PRINTED mana value BEFORE destroy; destroy it (skip
        // indestructible — the scan filter); if it was actually
        // destroyed AND its mv ≤ 2, create one Lander token under the
        // source's controller. Destroy-half clones the round-25/65
        // `DestroyTargetArtifact` / `DestroyTargetArtifactOrTapped
        // Creature` body verbatim with the filter swapped to
        // Artifact-OR-Enchantment. The Lander-create block is
        // re-derived privately (file-iso) from the `Effect::Create
        // Token` arm — registry-bounds check, fresh-id allocator,
        // source-controller seat, fresh etb_timestamp, ENTERS
        // dispatch queue. `token_printing_id` is the Lander's Rust
        // registry index (carried on the variant; Python's class is
        // field-free and uses TOKEN_PRINTINGS["Lander"] intrinsically
        // — the pid is dropped at the bridge). See invariant I39 /
        // I81 (source-controller token seat).
        //
        // **§2 indestructible parity**: the scan SKIPS indestructible
        // permanents (the shipped DestroyTargetArtifact precedent).
        // Python's `legal_targets` includes indestructible artifacts/
        // enchantments but `destroy()` returns False for them →
        // early-return, NO Lander consolation. An indestructible-ONLY
        // board reaches the SAME observable on both engines (no
        // destroy, no Lander). The probe pins single-legal-target
        // boards so the deterministic-first pick is unambiguous; a
        // mixed indestructible+destroyable board is not exercised
        // (different first-pick conventions — out of probe scope, as
        // with the Radiant Strike precedent).
        Effect::SeedshipImpactEffect { token_printing_id } => {
            let lander_pid: u32 = *token_printing_id;
            // Registry-bounds check up front (mirrors the CreateToken
            // arm's whole-or-nothing contract) — surface an unknown
            // pid before any state mutation.
            if state.registry.lookup(lander_pid).is_none() {
                return Err(PyValueError::new_err(format!(
                    "SeedshipImpactEffect token_printing_id \
                     {lander_pid} not in registry"
                )));
            }
            // Target scan: first Artifact OR Enchantment in
            // ETB-timestamp order across BOTH bfs, non-indestructible.
            // Capture the PRINTED mana value at scan time (read BEFORE
            // destroy — Python reads `obj.printing.mana_cost.total`
            // before `destroy(...)`; the printing is immutable so
            // scan-time == pre-destroy).
            let target: Option<(usize, u32, u32)> =
                crate::bf_iter::bf_iter_etb_sorted(state)
                    .into_iter()
                    .find_map(|obj| {
                        let printing =
                            state.registry.lookup(obj.printing_id)?;
                        let is_artifact = printing
                            .card_types
                            .iter()
                            .any(|t| t == "Artifact");
                        let is_enchantment = printing
                            .card_types
                            .iter()
                            .any(|t| t == "Enchantment");
                        if !(is_artifact || is_enchantment) {
                            return None;
                        }
                        if printing
                            .keywords
                            .iter()
                            .any(|k| k == "indestructible")
                        {
                            return None;
                        }
                        // Printed mana value = generic + all colored
                        // pips (Rust ManaCost has no hybrid/x field;
                        // the registry flattens hybrid at parse time —
                        // matches Python `mana_cost.total` for
                        // non-hybrid costs; the registry-level
                        // hybrid-flatten is the existing documented
                        // simplification, not new here).
                        let mc = &printing.mana_cost;
                        let mv: u32 = mc.generic as u32
                            + mc.white as u32
                            + mc.blue as u32
                            + mc.black as u32
                            + mc.red as u32
                            + mc.green as u32;
                        Some((obj.controller as usize, obj.id, mv))
                    });
            if let Some((pidx, target_id, mv)) = target {
                // ---- Destroy half (verbatim DestroyTargetArtifact
                // remove→graveyard + LTB + token-cease tail).
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id from scan but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                // CE13 closure: `summoning_sick` is NOT reset here
                // (CR 302.1 — battlefield-only state). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let (printing_id, leaving_obj_id) =
                    (obj.printing_id, obj.id);
                Arc::make_mut(&mut state.players[pidx].graveyard)
                    .push(obj);
                // Round-29 Void LTB: target is artifact/enchantment;
                // helper gates on the printing.
                mark_left_battlefield_if_nonland(state, printing_id);
                // R76-2 (audit of the verbatim-clone sibling — the
                // bench-resweep explicitly flagged this destroy-half
                // for the same omission). Python's `SeedshipImpact
                // Effect.resolve` calls the generic `turn.destroy`,
                // which fires `Event.DIES` for a CREATURE death (CR
                // 603 / 700.4). Seedship's filter is Artifact OR
                // Enchantment, but a dual-typed **Artifact Creature**
                // is admissible AND a creature — destroying it IS a
                // creature death and MUST fire its DIES trigger
                // byte-equal with Python. The verbatim destroy-clone
                // previously pushed ONLY LEAVES (same R76-2 class as
                // the Radiant Strike `DestroyTargetArtifactOrTapped
                // Creature` arm above). Creature-gated so a pure
                // (non-creature) artifact/enchantment does NOT fire a
                // spurious DIES. DIES pushed BEFORE LEAVES (the SBA /
                // R74-2 push order; LIFO -> LEAVES resolves first),
                // drained by the existing R74-2
                // `drain_pending_dies_dispatches` at the 4 resolution
                // sites.
                let victim_is_creature = state
                    .registry
                    .lookup(printing_id)
                    .map(|p| {
                        p.card_types
                            .iter()
                            .any(|t| t == "Creature")
                    })
                    .unwrap_or(false);
                if victim_is_creature {
                    state
                        .pending_dies_dispatches
                        .push(leaving_obj_id);
                }
                // Slice 10: LTB fan-out at the Effect arm.
                state.pending_leaves_dispatches.push(leaving_obj_id);
                // Round-55: token-cease sibling of the LEAVES push.
                crate::state_ops_zones::queue_token_cease(
                    state,
                    leaving_obj_id,
                );

                // ---- Conditional Lander rider: only when the target
                // was actually destroyed (it was — the scan already
                // excluded indestructible, matching Python's
                // `if not destroy(...): return` no-Lander-consolation)
                // AND its printed mv ≤ 2.
                if mv <= 2 {
                    // Source-controller seat (CR 111.4 — token under
                    // the spell's controller, not active_player). The
                    // in-tree stack resolver sets
                    // `current_resolve_source_controller` around its
                    // apply_effect loop (the I81 substrate); fall back
                    // to active_player for direct apply_effect_pub
                    // callers (back-compat).
                    let recipient: u8 = state
                        .current_resolve_source_controller
                        .unwrap_or(state.active_player);
                    // Fresh-id allocator: max id across every zone on
                    // both players + 1 (verbatim from the CreateToken
                    // arm; includes exile so r11+ exiled objects don't
                    // collide).
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
                            for o in zone.iter() {
                                if !found_any || o.id > max_id {
                                    max_id = o.id;
                                    found_any = true;
                                }
                            }
                        }
                    }
                    let new_id: u32 =
                        if found_any { max_id + 1 } else { 0 };
                    // Fresh etb_timestamp (CE4 closure — strictly
                    // monotonic so the snapshot/fingerprint walk
                    // orders this token after prior ETBs).
                    let tok_etb = state.next_etb_timestamp;
                    state.next_etb_timestamp =
                        state.next_etb_timestamp.saturating_add(1);
                    let bf: &mut Vec<GameObject> = Arc::make_mut(
                        &mut state.players[recipient as usize]
                            .battlefield,
                    );
                    bf.push(GameObject {
                        id: new_id,
                        printing_id: lander_pid,
                        controller: recipient,
                        zone: ZONE_BATTLEFIELD,
                        tapped: false,
                        summoning_sick: true,
                        damage: 0,
                        counters: 0,
                        charge_counters: 0,
                        loyalty_counters: 0,
                        attached_to: None,
                        exiled_with_source: None,
                        stun_counters: 0,
                        etb_timestamp: tok_etb,
                        ueot_modifiers: Vec::new(),
                        warp_exile_pending: false,
                        warped: false,
                    });
                    // ETB-trigger Slice 2 (RS4): queue ENTERS for the
                    // fresh token; drained by the surrounding resolver
                    // after the resolving spell's stack item pops.
                    state.pending_etb_dispatches.push(new_id);
                }
            }
        }
        // DealDamageToTargetCreatureWithExcessLanderRider
        // (Effect-uncovered Tier-A — Orbital Plunge, Lander-rider).
        // Mirrors Python's
        // `DealDamageToTargetCreatureWithExcessLanderRider.resolve`
        // (`effects/generic/damage.py:357`): pick the target creature
        // (IsCreature slot; deterministic-first scan over BOTH
        // battlefields in ETB-timestamp order — Python's centralized
        // `state.battlefield` walk + `_slot_target_still_legal`
        // re-check, the established no-callback first-creature
        // campaign convention); compute `remaining = max(0,
        // effective_toughness − obj.damage)` and `excess = max(0,
        // amount − remaining)` BEFORE applying damage; apply `amount`
        // via `obj.damage.saturating_add`; if `excess > 0` create one
        // Lander under the source's controller. Lifelink/deathtouch
        // NOT modeled (Python parity — the documented simplification).
        //
        // **§2 counters-asymmetry (load-bearing, the mini-spec risk).**
        // Python's `effective_toughness` folds `+1/+1` counters (CR
        // 613 layer 7d). The combat-side Rust getter deliberately does
        // NOT, but the SBA lethal check DOES via `base + obj.counters
        // + ueot_toughness_bonus()`. To stay byte-equal with the
        // Python SoT, the remaining-lethal denominator here is
        // computed with the counters-INCLUSIVE formula re-derived
        // privately (file-iso): `base = ueot_base_pt_override().t OR
        // printed_toughness`, then `+ obj.counters +
        // obj.ueot_toughness_bonus()` — the exact
        // `state_ops_sba.rs::collect_sba_victims` shape. Pinned by a
        // +1/+1-counter'd target so a wrong accessor can't silently
        // diverge the excess.
        Effect::DealDamageToTargetCreatureWithExcessLanderRider {
            amount,
            token_printing_id,
        } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "DealDamageToTargetCreatureWithExcessLanderRider \
                     amount must be non-negative, got {amount}"
                )));
            }
            let lander_pid: u32 = *token_printing_id;
            if state.registry.lookup(lander_pid).is_none() {
                return Err(PyValueError::new_err(format!(
                    "DealDamageToTargetCreatureWithExcessLanderRider \
                     token_printing_id {lander_pid} not in registry"
                )));
            }
            let dmg: i32 = *amount;
            // Target = first creature in ETB-timestamp order across
            // BOTH bfs (the IsCreature TargetSpec; Python's
            // `state.battlefield` centralized walk + the
            // deterministic-first no-callback convention).
            let target: Option<(usize, u32)> =
                crate::bf_iter::bf_iter_etb_sorted(state)
                    .into_iter()
                    .find_map(|obj| {
                        let printing =
                            state.registry.lookup(obj.printing_id)?;
                        if printing
                            .card_types
                            .iter()
                            .any(|t| t == "Creature")
                        {
                            Some((obj.controller as usize, obj.id))
                        } else {
                            None
                        }
                    });
            if let Some((pidx, target_id)) = target {
                // Compute excess BEFORE mutating damage. Counters-
                // inclusive effective toughness (the Python-SoT view —
                // collect_sba_victims shape; NOT the combat-side
                // getter which omits counters).
                let (eff_tough, prior_damage): (i32, i32) = {
                    let obj = state.players[pidx]
                        .battlefield
                        .iter()
                        .find(|o| o.id == target_id)
                        .expect("target_id from scan but not found");
                    let printing = state
                        .registry
                        .lookup(obj.printing_id)
                        .expect("scanned printing must resolve");
                    let printed_t = printing.toughness.unwrap_or(0) as i32;
                    let base_t = obj
                        .ueot_base_pt_override()
                        .map(|(_, t)| t)
                        .unwrap_or(printed_t);
                    let eff = base_t
                        + obj.counters
                        + obj.ueot_toughness_bonus();
                    (eff, obj.damage as i32)
                };
                let remaining: i32 = (eff_tough - prior_damage).max(0);
                let excess: i32 = (dmg - remaining).max(0);
                // Apply `amount` damage (DealDamageAnyTarget shape:
                // saturating_add into the i16 damage field).
                let dmg_i16 = dmg.min(i16::MAX as i32) as i16;
                {
                    let bf_mut: &mut Vec<GameObject> = Arc::make_mut(
                        &mut state.players[pidx].battlefield,
                    );
                    for o in bf_mut.iter_mut() {
                        if o.id == target_id {
                            o.damage = o.damage.saturating_add(dmg_i16);
                            break;
                        }
                    }
                }
                // Conditional Lander rider: only when excess damage
                // was dealt (CR 120.10 — at-resolve excess, NO
                // damaged-this-turn ledger; the Faller's-r57 lesson).
                if excess > 0 {
                    // Source-controller seat (CR 111.4). The in-tree
                    // stack resolver sets
                    // `current_resolve_source_controller`; fall back
                    // to active_player (back-compat for direct
                    // apply_effect_pub callers).
                    let recipient: u8 = state
                        .current_resolve_source_controller
                        .unwrap_or(state.active_player);
                    // Fresh-id allocator: max id across every zone on
                    // both players + 1 (verbatim CreateToken shape).
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
                            for o in zone.iter() {
                                if !found_any || o.id > max_id {
                                    max_id = o.id;
                                    found_any = true;
                                }
                            }
                        }
                    }
                    let new_id: u32 =
                        if found_any { max_id + 1 } else { 0 };
                    let tok_etb = state.next_etb_timestamp;
                    state.next_etb_timestamp =
                        state.next_etb_timestamp.saturating_add(1);
                    let bf: &mut Vec<GameObject> = Arc::make_mut(
                        &mut state.players[recipient as usize]
                            .battlefield,
                    );
                    bf.push(GameObject {
                        id: new_id,
                        printing_id: lander_pid,
                        controller: recipient,
                        zone: ZONE_BATTLEFIELD,
                        tapped: false,
                        summoning_sick: true,
                        damage: 0,
                        counters: 0,
                        charge_counters: 0,
                        loyalty_counters: 0,
                        attached_to: None,
                        exiled_with_source: None,
                        stun_counters: 0,
                        etb_timestamp: tok_etb,
                        ueot_modifiers: Vec::new(),
                        warp_exile_pending: false,
                        warped: false,
                    });
                    state.pending_etb_dispatches.push(new_id);
                }
            }
        }
        // DepressurizeEffect (Effect-uncovered Tier-A — Depressurize).
        // Mirrors Python's `DepressurizeEffect.resolve`
        // (`effects/bespoke.py:1554`): target = first creature
        // (Python's `legal_targets` is ANY creature — NOT controller-
        // restricted, the verified deviation from the bare pump arm;
        // scan BOTH bfs in ETB-timestamp order, Python's centralized
        // `state.battlefield` walk + the deterministic-first
        // convention); push a `−power_penalty/−0` UEOT
        // `PowerToughnessBonus`; then read POST-UEOT EFFECTIVE power
        // and `if eff_power <= 0` destroy it (respecting
        // indestructible — CR 702.12; Python's `turn.destroy` gate).
        //
        // **§2 counters-asymmetry (load-bearing, the mini-spec
        // risk).** Python's `effective_power`
        // (`game._compute_effective_pt`) folds the just-pushed UEOT
        // bonus AND `+1/+1` counters (CR 613 layer 7c+7d). Rust's
        // combat-side `effective_power` getter folds the UEOT bonus
        // but NOT counters. To stay byte-equal with the Python SoT,
        // the conditional reads the counters-INCLUSIVE effective
        // power re-derived privately (file-iso): `base =
        // ueot_base_pt_override().p OR printed_power`, plus
        // `obj.counters`, plus `obj.ueot_power_bonus()` (which now
        // includes the −pp just pushed). A combat-getter read would
        // silently diverge on a counter'd target — pinned.
        Effect::DepressurizeEffect { power_penalty } => {
            let pp: i32 = *power_penalty;
            // Target = first creature in ETB-timestamp order across
            // BOTH bfs (any creature — Depressurize's legal_targets
            // is NOT controller-restricted).
            let target: Option<(usize, u32)> =
                crate::bf_iter::bf_iter_etb_sorted(state)
                    .into_iter()
                    .find_map(|obj| {
                        let printing =
                            state.registry.lookup(obj.printing_id)?;
                        if printing
                            .card_types
                            .iter()
                            .any(|t| t == "Creature")
                        {
                            Some((obj.controller as usize, obj.id))
                        } else {
                            None
                        }
                    });
            if let Some((pidx, target_id)) = target {
                // Push the −pp/−0 UEOT modifier (verbatim from the
                // PumpTargetCreatureUntilEOT push shape).
                {
                    let zone: &mut Vec<GameObject> = Arc::make_mut(
                        &mut state.players[pidx].battlefield,
                    );
                    for o in zone.iter_mut() {
                        if o.id == target_id {
                            o.ueot_modifiers.push(
                                UeotModifier::PowerToughnessBonus {
                                    power: -pp,
                                    toughness: 0,
                                },
                            );
                            break;
                        }
                    }
                }
                // Read POST-UEOT effective power, counters-inclusive
                // (the Python-SoT view; NOT the combat-side getter
                // which omits counters). base = ueot base override
                // (.p) OR printed power; + obj.counters +
                // obj.ueot_power_bonus() (now includes the −pp).
                let (eff_power, is_indestructible): (i32, bool) = {
                    let o = state.players[pidx]
                        .battlefield
                        .iter()
                        .find(|x| x.id == target_id)
                        .expect("target_id from scan but not found");
                    let printing = state
                        .registry
                        .lookup(o.printing_id)
                        .expect("scanned printing must resolve");
                    let printed_p = printing.power.unwrap_or(0) as i32;
                    let base_p = o
                        .ueot_base_pt_override()
                        .map(|(p, _)| p)
                        .unwrap_or(printed_p);
                    let eff =
                        base_p + o.counters + o.ueot_power_bonus();
                    let indest = printing
                        .keywords
                        .iter()
                        .any(|k| k == "indestructible")
                        || o.ueot_has_keyword("indestructible");
                    (eff, indest)
                };
                // "Then if that creature's power is 0 or less,
                // destroy it." Python's `turn.destroy` respects
                // indestructible (CR 702.12 — the pump still applied,
                // only the destroy is suppressed).
                if eff_power <= 0 && !is_indestructible {
                    let bf_mut: &mut Vec<GameObject> = Arc::make_mut(
                        &mut state.players[pidx].battlefield,
                    );
                    let pos = bf_mut
                        .iter()
                        .position(|o| o.id == target_id)
                        .expect("target_id present but not found");
                    let mut obj = bf_mut.remove(pos);
                    obj.zone = ZONE_GRAVEYARD;
                    obj.tapped = false;
                    // CE13: summoning_sick NOT reset (CR 302.1, I35).
                    obj.damage = 0;
                    // CFI-1: counters are NOT cleared on the dead
                    // object. Python's `turn.move_off_battlefield`
                    // (turn.py) clears combat marks (damage / tapped /
                    // attached_to) but deliberately leaves `+1/+1`
                    // counters intact; the SBA destroy path
                    // (`state_ops_sba.rs` ~:417) follows that observable
                    // ("counters retained on the dead object" — the
                    // established byte-equal contract, pinned by the
                    // Orbital Plunge probe). A prior stray
                    // `obj.counters = 0;` here diverged from BOTH Python
                    // (SoT) and Rust's own SBA destroy path; removed so
                    // a counter'd creature destroyed by Depressurize
                    // carries its counters into the graveyard byte-equal
                    // (CFI-1 closed; see the FINDINGS NOTE in
                    // tests/test_probe_cross_feature_interaction.py).
                    obj.attached_to = None;
                    obj.exiled_with_source = None;
                    let (printing_id, leaving_obj_id) =
                        (obj.printing_id, obj.id);
                    Arc::make_mut(
                        &mut state.players[pidx].graveyard,
                    )
                    .push(obj);
                    mark_left_battlefield_if_nonland(
                        state, printing_id,
                    );
                    // R74-2: a "destroy" of a creature is a death (CR
                    // 700.4) — its `Event.DIES` triggered abilities
                    // MUST fire, exactly as the generic SBA destroy
                    // path does (`state_ops_sba.rs` ~:467-482) and as
                    // Python's `turn.destroy` -> `move_off_battlefield`
                    // does (`turn.py:253-283`: `_fire_dies_triggers` +
                    // the predicate-path `dispatch_event(DIES)` BEFORE
                    // `_fire_leaves_battlefield_triggers`). The prior
                    // hand-rolled arm pushed ONLY
                    // `pending_leaves_dispatches`, so a destroyed
                    // dies-trigger creature (e.g. Gravpack Monoist ->
                    // Robot token) silently never fired its trigger —
                    // a Rust-side divergence from the Python SoT
                    // surfaced by the round-74 post-spell-admit bench
                    // sweep. Push order mirrors the SBA path + the
                    // `Event::LeavesBattlefield` cards.rs doc-comment
                    // contract (DIES first via
                    // `pending_dies_dispatches`, LEAVES second via
                    // `pending_leaves_dispatches`); the matching
                    // resolution-path drain order (DIES drained then
                    // LEAVES; LIFO -> LEAVES resolves first) preserves
                    // Python's `move_off_battlefield` sequence.
                    // Creature-gated like the SBA path so a
                    // type-changed non-creature does not fire a
                    // spurious DIES (CR 700.4 — Depressurize's scan
                    // already filters to creatures, but the gate keeps
                    // the SBA-path invariant byte-equal).
                    let victim_is_creature = state
                        .registry
                        .lookup(printing_id)
                        .map(|p| {
                            p.card_types
                                .iter()
                                .any(|t| t == "Creature")
                        })
                        .unwrap_or(false);
                    if victim_is_creature {
                        state
                            .pending_dies_dispatches
                            .push(leaving_obj_id);
                    }
                    state
                        .pending_leaves_dispatches
                        .push(leaving_obj_id);
                    crate::state_ops_zones::queue_token_cease(
                        state,
                        leaving_obj_id,
                    );
                }
            }
        }
        // BiosynthicBurstEffect (Effect-uncovered Tier-A — Biosynthic
        // Burst). Mirrors Python's `BiosynthicBurstEffect.resolve`
        // (`effects/bespoke.py:1487`): own-creature target;
        // `add_plus_one_counters(state, obj, 1)`;
        // `ApplyEffect(GrantKeywords({reach,trample,indestructible}),
        // EndOfTurn()).resolve(...)`; `obj.tapped = False`.
        //
        // **Controller-restricted scan (verified deviation, pinned).**
        // Python's `legal_targets` IS controller-restricted
        // (`o.controller_id == controller_id`, bespoke.py:1484) —
        // UNLIKE `DepressurizeEffect` whose legal_targets is ANY
        // creature. So this scan walks ONLY the source-controller's
        // battlefield (the same controller-only first-creature scan
        // `PutPlusOneCounterOnCreatureYouControl` `:7721` and
        // `GrantKeywordsToTargetCreatureUntilEOT` `:10509` use), NOT
        // both bfs via `bf_iter_etb_sorted`. `resolve` also re-guards
        // `obj.controller_id == controller_id` after target
        // selection — the scan already enforces it.
        //
        // **Counter shape (the established byte-equal mapping).** The
        // +1/+1 counter is `obj.counters.saturating_add(1)` — the
        // EXACT shape `PutPlusOneCounterOnCreatureYouControl` `:7780`
        // uses. Python's `add_plus_one_counters` writes
        // `obj.plus_one_counters`; the cross-engine bridge maps that
        // to Rust's signed scalar `obj.counters` (cross_engine.py
        // ~:1276 "mirrors Rust's scalar"). Python's
        // counter-doubling-replacement / Terrasymbiosis observer
        // fan-out is NOT replicated here — the proven sibling arm
        // makes the identical simplification (no doubler / no
        // counters-added trigger in the EoE pool); documented in
        // `docs/SEARCH_LIMITATIONS.md`.
        //
        // **3-keyword UEOT grant (the proven push shape).** Re-derive
        // the `GrantKeywordsToTargetCreatureUntilEOT` `:10559` push
        // privately: for each of {reach, trample, indestructible}
        // push `UeotModifier::GrantKeyword { keyword }` (lowercase,
        // exactly as that arm does). That arm's continuous_effects ↔
        // ueot_modifiers equivalence is already cross-engine-proven
        // byte-equal (Python's `GrantKeywords` calls
        // `state.add_continuous_effect(layer=6, kind="grant_keyword")`
        // wrapped in `ApplyEffect(..., EndOfTurn())`; the harness
        // proves the mapping). The UEOT keywords drain at the
        // cleanup step on BOTH engines (the round-39 SBA-on-0/0
        // class — indestructible protects THROUGH the end-of-turn
        // SBA, then the keyword expires at cleanup; pinned).
        Effect::BiosynthicBurstEffect => {
            // Locate source controller (5-zone walk; identical to the
            // `PutPlusOneCounterOnCreatureYouControl` /
            // `GrantKeywordsToTargetCreatureUntilEOT` siblings).
            let mut src_controller: Option<u8> = None;
            'bb_outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) =
                        zone.iter().find(|o| o.id == source_obj_id)
                    {
                        src_controller = Some(obj.controller);
                        break 'bb_outer;
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
            if let Some(controller) = src_controller {
                let cidx = controller as usize;
                // Pick first creature on the CONTROLLER's bf (the
                // controller-restricted deviation — Python's
                // legal_targets is controller-only).
                let target_id: Option<u32> = {
                    let bf = &state.players[cidx].battlefield;
                    let registry = &state.registry;
                    bf.iter().find_map(|obj| {
                        let printing = registry
                            .printings
                            .get(obj.printing_id as usize)?;
                        if printing
                            .card_types
                            .iter()
                            .any(|t| t == "Creature")
                        {
                            Some(obj.id)
                        } else {
                            None
                        }
                    })
                };
                if let Some(target_id) = target_id {
                    let zone: &mut Vec<GameObject> = Arc::make_mut(
                        &mut state.players[cidx].battlefield,
                    );
                    for obj in zone.iter_mut() {
                        if obj.id == target_id {
                            // +1/+1 counter (the established
                            // saturating_add scalar shape).
                            obj.counters =
                                obj.counters.saturating_add(1);
                            // 3-keyword UEOT grant (the proven
                            // GrantKeyword push shape, lowercase).
                            for kw in
                                ["reach", "trample", "indestructible"]
                            {
                                obj.ueot_modifiers.push(
                                    UeotModifier::GrantKeyword {
                                        keyword: kw.to_string(),
                                    },
                                );
                            }
                            // Untap it.
                            obj.tapped = false;
                            break;
                        }
                    }
                }
                // No own creature → silent no-op (Python returns
                // early on empty legal_targets / non-creature).
            }
        }
        // FocusFireEffect (Effect-uncovered Tier-A — Focus Fire). The
        // FIRST effect-resolve arm to READ combat-declaration state.
        // Mirrors Python's `FocusFireEffect.resolve` /
        // `FocusFireEffect._amount` (`effects/bespoke.py:1784/1792`):
        // deal `(base + |source-controller's creatures∪Spacecraft|)`
        // damage to the first attacking-or-blocking creature.
        //
        // **The set-union denominator (the §2 subtle-divergence
        // pin).** Walk the source-controller's bf ONCE; +1 for each
        // obj whose `printing.card_types` contains "Creature" OR
        // "Spacecraft". A dual-typed Artifact Creature Spacecraft is
        // ONE `Vec` element → counts ONCE. This is NOT a sum of a
        // creature-count and a spacecraft-count (that double-counts
        // dual-typed permanents). BIT-FOR-BIT mirrors Python's
        // `base + sum(1 for o in state.battlefield if o.controller_id
        // == controller_id and (o.printing.is_creature or
        // o.printing.is_spacecraft))` — the `or` is on the object.
        //
        // **The combat predicate (verify-first-confirmed byte-equal
        // Python↔Rust).** A creature is attacking iff its id is in
        // `state.attackers` (`Vec<u32>`); blocking iff its id appears
        // as a `blocker_id` in `state.blockers` (`Vec<(attacker_id,
        // blocker_id)>`). This is the EXACT pair `declare_attacker`
        // (`state_ops_combat.rs:681`) / `declare_blocker` (`:772`)
        // push and the multi-blocker cross-engine probes have proven
        // byte-equal vs Python's `obj.attacking` /
        // `obj.blocking is not None`. Python re-checks
        // `_slot_target_still_legal` at resolve (CR 608.2b); if no
        // creature is attacking-or-blocking the spell still resolves
        // and the damage fizzles (silent no-op).
        //
        // **Target scan = deterministic-first across BOTH bfs in
        // ETB-timestamp order** (Python's filter is NOT controller-
        // restricted — `IsCreature ∧ (IsAttacking ∨ IsBlocking)`,
        // ANY creature; the same `bf_iter_etb_sorted` +
        // deterministic-first convention `DepressurizeEffect` `:5889`
        // uses, the cross-engine spell-card-bridge `_PickFirstLegal
        // TargetAgent` mirrors it). Damage applied via
        // `obj.damage.saturating_add` (the `DealDamageAnyTarget`
        // shape).
        Effect::FocusFireEffect { base } => {
            // Source-controller resolution (5-zone walk + stack scan;
            // the established sister shape — `DealDamageToOpponent
            // CreatureByCreaturesYouControl` `:7065`,
            // `BiosynthicBurstEffect` `:6040`).
            let mut src_controller: Option<u8> = None;
            'ff_outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) =
                        zone.iter().find(|o| o.id == source_obj_id)
                    {
                        src_controller = Some(obj.controller);
                        break 'ff_outer;
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
                return Ok(()); // source not found: silent fizzle
            };
            // Set-union denominator: ONE pass over the source-
            // controller's bf; +1 if Creature OR Spacecraft (the `||`
            // is on the object — a dual-typed obj is one Vec element,
            // counts ONCE; NOT a two-scan sum).
            let cidx = controller as usize;
            let mut x: i32 = *base;
            for obj in state.players[cidx].battlefield.iter() {
                let Some(printing) = state
                    .registry
                    .printings
                    .get(obj.printing_id as usize)
                else {
                    continue;
                };
                if printing
                    .card_types
                    .iter()
                    .any(|t| t == "Creature" || t == "Spacecraft")
                {
                    x = x.saturating_add(1);
                }
            }
            // Target = first attacking-or-blocking creature in ETB-
            // timestamp order across BOTH bfs (NOT controller-
            // restricted — Python's filter is ANY creature). Combat
            // predicate: id in `state.attackers` OR id is a
            // `blocker_id` in `state.blockers`.
            let target: Option<(usize, u32)> = {
                let attackers = &state.attackers;
                let blockers = &state.blockers;
                let registry = &state.registry;
                crate::bf_iter::bf_iter_etb_sorted(state)
                    .into_iter()
                    .find_map(|obj| {
                        let printing =
                            registry.lookup(obj.printing_id)?;
                        if !printing
                            .card_types
                            .iter()
                            .any(|t| t == "Creature")
                        {
                            return None; // not a creature
                        }
                        let is_attacking =
                            attackers.contains(&obj.id);
                        let is_blocking = blockers
                            .iter()
                            .any(|(_att, blk)| *blk == obj.id);
                        if is_attacking || is_blocking {
                            Some((obj.controller as usize, obj.id))
                        } else {
                            None
                        }
                    })
            };
            if let Some((pidx, target_id)) = target {
                let amount_i16 = x.min(i16::MAX as i32) as i16;
                let bf_mut: &mut Vec<GameObject> = Arc::make_mut(
                    &mut state.players[pidx].battlefield,
                );
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage =
                            obj.damage.saturating_add(amount_i16);
                        break;
                    }
                }
            }
            // else: no attacking/blocking creature → silent fizzle
            // (CR 608.2b — the spell resolves, damage is not dealt;
            // Python's `_slot_target_still_legal` returns early).
        }
        // DiplomaticRelationsEffect (Effect-uncovered Tier-A #7 —
        // Diplomatic Relations; spell-card-bridge Phase 2). The
        // FIRST 2-slot heterogeneous-target spell arm. Mirrors
        // Python's `DiplomaticRelationsEffect.resolve`
        // (`effects/bespoke.py:1940-2008`) BIT-FOR-BIT against the
        // Python source of truth:
        //  - slot 0 (friendly pumped creature) rides on
        //    `current_resolve_payload_target_id` (swapped in by both
        //    resolve entry points from `StackItem.target_obj_id`);
        //  - slot 1 (opponent's damaged creature) rides on
        //    `current_resolve_payload_target_id_2` (from
        //    `StackItem.target_obj_id_2`).
        // Python: pump slot-0 +1/+0 + vigilance UEOT (target
        // re-validated: still on a bf AND still caster-controlled,
        // else the WHOLE effect fizzles — `my_obj=None` short-
        // circuits before damage too); then if slot-1 exists +
        // is opponent-controlled, deal slot-0's POST-PUMP effective
        // power (counters-inclusive) as damage.
        Effect::DiplomaticRelationsEffect => {
            // Source-controller resolution (the established sister
            // 5-zone-walk + stack-scan shape — `BiosynthicBurst
            // Effect` `:6091`, `FocusFireEffect` `:6215`). This is
            // the caster (= `controller_id` in Python's `resolve`).
            let mut src_controller: Option<u8> = None;
            'dr_outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) =
                        zone.iter().find(|o| o.id == source_obj_id)
                    {
                        src_controller = Some(obj.controller);
                        break 'dr_outer;
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
                return Ok(()); // source not found: silent fizzle
            };
            // Slot 0: the friendly pumped creature. Read the bound
            // target, re-validate (CR 608.2b — Python re-checks the
            // creature is on a bf AND still controlled by the
            // caster, else `my_obj = None` and the WHOLE effect is a
            // no-op — NO damage either).
            let slot0_id = state.current_resolve_payload_target_id;
            let mut my_pidx: Option<usize> = None;
            if let Some(t0) = slot0_id {
                'find0: for (pidx, player) in
                    state.players.iter().enumerate()
                {
                    if let Some(obj) = player
                        .battlefield
                        .iter()
                        .find(|o| o.id == t0)
                    {
                        // Still controlled by the caster?
                        if obj.controller == controller {
                            my_pidx = Some(pidx);
                        }
                        break 'find0;
                    }
                }
            }
            let (Some(my_pidx), Some(my_id)) = (my_pidx, slot0_id)
            else {
                // slot-0 illegal at resolve → whole effect fizzles
                // (Python: `my_obj = None` → early return before
                // damage). Silent no-op.
                return Ok(());
            };
            // Pump slot-0 +1/+0 UEOT + grant vigilance UEOT — the
            // EXACT push shapes the cross-engine-proven
            // `DepressurizeEffect` (PowerToughnessBonus) /
            // `BiosynthicBurstEffect` (GrantKeyword, lowercase) arms
            // use. Both drain at cleanup byte-equal on both engines.
            {
                let zone: &mut Vec<GameObject> = Arc::make_mut(
                    &mut state.players[my_pidx].battlefield,
                );
                for obj in zone.iter_mut() {
                    if obj.id == my_id {
                        obj.ueot_modifiers.push(
                            UeotModifier::PowerToughnessBonus {
                                power: 1,
                                toughness: 0,
                            },
                        );
                        obj.ueot_modifiers.push(
                            UeotModifier::GrantKeyword {
                                keyword: "vigilance".to_string(),
                            },
                        );
                        break;
                    }
                }
            }
            // Slot 1: the opponent's damaged creature. Read the
            // second bound target, re-validate (must be on a bf AND
            // controlled by a NON-caster — Python checks
            // `opp_obj.controller_id != controller_id`). If
            // illegal/absent, the pump already applied and the
            // damage component is skipped (Python returns after the
            // pump in that branch).
            let slot1_id = state.current_resolve_payload_target_id_2;
            let mut opp_pidx: Option<usize> = None;
            if let Some(t1) = slot1_id {
                'find1: for (pidx, player) in
                    state.players.iter().enumerate()
                {
                    if let Some(obj) = player
                        .battlefield
                        .iter()
                        .find(|o| o.id == t1)
                    {
                        if obj.controller != controller {
                            opp_pidx = Some(pidx);
                        }
                        break 'find1;
                    }
                }
            }
            let (Some(opp_pidx), Some(opp_id)) = (opp_pidx, slot1_id)
            else {
                return Ok(()); // pump applied, damage component
                               // fizzles — Python early return.
            };
            // Damage = slot-0's POST-PUMP EFFECTIVE power, counters-
            // INCLUSIVE (Python's `effective_power` view — the EXACT
            // counters-inclusive formula re-derived privately per
            // the file-isolation rule, identical to the
            // `DepressurizeEffect` conditional read `:5928-5951`:
            // base = ueot_base_pt_override().p OR printed_power,
            // plus obj.counters, plus obj.ueot_power_bonus() — which
            // now includes the just-pushed +1).
            let amount: i32 = {
                let o = state.players[my_pidx]
                    .battlefield
                    .iter()
                    .find(|x| x.id == my_id)
                    .expect("slot-0 id validated but not found");
                let printing = state
                    .registry
                    .lookup(o.printing_id)
                    .expect("slot-0 printing must resolve");
                let printed_p = printing.power.unwrap_or(0) as i32;
                let base_p = o
                    .ueot_base_pt_override()
                    .map(|(p, _)| p)
                    .unwrap_or(printed_p);
                base_p + o.counters + o.ueot_power_bonus()
            };
            // Apply damage to slot-1 via the proven
            // `obj.damage.saturating_add` primitive shape
            // (`DealDamageAnyTarget` / `FocusFireEffect`). SBA
            // handles lethal post-resolve byte-equal. Applied
            // UNCONDITIONALLY (no `amount > 0` clamp): Python's
            // `_apply_damage` does `obj.damage += amount`
            // unconditionally — `effective_power` is NOT clamped to
            // 0 (`game.py:_compute_effective_pt`), so a byte-equal
            // mirror must add the (rare) non-positive amount too.
            // With the just-pushed +1/+0 the realistic amount is
            // >= 1 for any non-negative-power creature; the
            // unconditional add only matters for a theoretically
            // negative effective power, where matching Python's
            // unclamped `+=` is the byte-equal contract. `saturating
            // _add` on the i16 mirrors Python's unbounded int add
            // for the realistic damage range (same shape as the
            // proven FocusFire/DealDamageAnyTarget arms).
            let amount_i16 = amount
                .clamp(i16::MIN as i32, i16::MAX as i32)
                as i16;
            let bf_mut: &mut Vec<GameObject> = Arc::make_mut(
                &mut state.players[opp_pidx].battlefield,
            );
            for obj in bf_mut.iter_mut() {
                if obj.id == opp_id {
                    obj.damage =
                        obj.damage.saturating_add(amount_i16);
                    break;
                }
            }
        }
        // DestroyTargetLand. CR 701.7 with Land filter — Dust Bowl /
        // Petrified Field pattern. Walks BOTH players' battlefield
        // in ETB-timestamp order via the shared
        // `crate::bf_iter::bf_iter_etb_sorted` helper, picking the
        // first Land that is not indestructible. Mirrors Python's
        // `effects/generic/destroy.py:DestroyTargetLand`
        // `TargetSpec(IsLand())` filter against the centralized
        // `state.battlefield` walk (no controller restriction). See
        // invariant I39.
        Effect::DestroyTargetLand => {
            let target: Option<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
                .into_iter()
                .find_map(|obj| {
                    let printing = state.registry.lookup(obj.printing_id)?;
                    if !printing.card_types.iter().any(|t| t == "Land") {
                        return None; // not a land
                    }
                    if printing.keywords.iter().any(|k| k == "indestructible") {
                        return None;
                    }
                    Some((obj.controller as usize, obj.id))
                });
            if let Some((pidx, target_id)) = target {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id from scan but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                // CE13 closure: `summoning_sick` is NOT reset here.
                // Python's `turn.move_off_battlefield` deliberately
                // omits the clear (CR 302.1 — sickness is battlefield-
                // only state). See I35.
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
                Arc::make_mut(&mut state.players[pidx].graveyard).push(obj);
                // Round-29 Void LTB: target is a Land by filter, so the
                // helper short-circuits to no-op — but call it anyway
                // for uniformity (the gate lives in one place, every
                // bf-exit site goes through the same code path).
                mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
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
            // **Controller resolution (I67 follow-up to the I59 /
            // I60 / I63 / I64 / I65 / I66 controller-of-effect
            // substrate).** Prefer the transient
            // `state.current_resolve_source_controller` (set by the
            // stack resolver around each `apply_effect` call),
            // falling back to `state.active_player` for back-compat
            // with direct `apply_effect_pub` callers. Same pattern
            // as `Effect::DealDamage` / `Effect::DamageEachOpponent`
            // — CR 119.5 / 608.2: an effect resolves under its
            // source's controller. For DealDamageAnyTarget, "any
            // target" defaulting to "the defender" means "the
            // SOURCE'S controller's opponent", not "the active
            // player's opponent".
            //
            // **Why the fix.** Pre-fix this arm computed
            // `defender_idx = 1 - state.active_player`. Wrong when
            // the resolving spell / triggered ability has a
            // controller != active_player. Worst-case example: p1's
            // creature has an ETB "deal 2 damage to any target"
            // trigger that fires on p0's turn (a p0 flicker
            // re-ETBs p1's creature). Pre-fix the trigger self-
            // damaged p1's first creature / life (defender_idx =
            // 1 - 0 = 1). Post-fix it correctly targets p0's first
            // creature / life (the trigger's controller's
            // opponent).
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            let defender_idx = 1 - controller;
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
        Effect::PumpTargetCreatureUntilEotGrantDiesReturnTapped {
            power_bonus,
            toughness_bonus,
        } => {
            // BLOCKED-RUST-EFFECT slice (round 60) — Perigee Beckoner
            // ETB. Same source-controller scan + first-creature-on-
            // own-bf target pick as `PumpTargetCreatureUntilEOT`, with
            // the "ANOTHER target creature you control" exclusion
            // (the chosen target must NOT be the source object — CR
            // 115.4 "another"). Push BOTH the +P/+T pump AND the
            // `GrantedDiesReturnTapped` marker the SBA destroy path
            // honors. (0/0) is still a legal target-and-mark op (the
            // rider applies even at +0/+0 — Perigee is +2/+0 but the
            // marker, not the pump, is the load-bearing observable),
            // so unlike the bare pump arm there is NO (0,0) short-
            // circuit. Empty / only-self own-bf → silent fizzle
            // (Python's non-optional `if not legal_targets: return`).
            let Some((cidx, target_id)) =
                perigee_pick_another_own_creature(state, source_obj_id)
            else {
                return Ok(()); // untrackable / no eligible OTHER creature
            };
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in zone.iter_mut() {
                if obj.id == target_id {
                    obj.ueot_modifiers.push(UeotModifier::PowerToughnessBonus {
                        power: *power_bonus,
                        toughness: *toughness_bonus,
                    });
                    obj.ueot_modifiers
                        .push(UeotModifier::GrantedDiesReturnTapped);
                    break;
                }
            }
        }
        // BLOCKED-RUST-EFFECT slice (round 31). Double target
        // creature's power UEOT — snapshot the chosen target's
        // effective power AT RESOLVE TIME and push that as a
        // PowerToughnessBonus { power: snapshot, toughness: 0 }
        // UEOT modifier. Subsequent counter gains / pumps within the
        // turn do NOT re-double (mirrors Python's snapshot semantic
        // at pump.py:234-236).
        //
        // Source-controller resolution mirrors the
        // PumpTargetCreatureUntilEOT shape: prefer the I79
        // current_resolve_source_controller transient slot, fall
        // back to scanning every zone for the source object, and
        // ultimately default to active_player. The target picker
        // walks the source-controller's bf and picks the FIRST
        // creature (smallest Vec index — same shape as
        // PumpTargetCreatureUntilEOT). Snapshot is read via the
        // private `read_battlefield_creature_power` helper already in
        // place from the round-17 Fight slice (per the per-slice
        // file-isolation rule).
        //
        // Fizzle cases (silent — no modifier pushed):
        // - source-controller untrackable → silent fizzle (defaults
        //   to active_player after the I79 fallback chain so this is
        //   rare in practice).
        // - source-controller has no creatures on bf → silent fizzle.
        // - chosen target's effective power ≤ 0 at resolve time →
        //   silent fizzle (matches Python's `if snapshot <= 0:
        //   return` guard at pump.py:235).
        Effect::DoubleTargetCreaturesPowerUEOT => {
            // Source-controller resolution (I79 substrate).
            let src_controller: u8 = state
                .current_resolve_source_controller
                .or_else(|| {
                    for player in &state.players {
                        for zone in [
                            &player.hand,
                            &player.library,
                            &player.battlefield,
                            &player.graveyard,
                            &player.exile,
                        ] {
                            if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                                return Some(obj.controller);
                            }
                        }
                    }
                    None
                })
                .unwrap_or(state.active_player);
            let cidx = src_controller as usize;
            // Pick the first creature on the source-controller's bf.
            // Creature-ness gates on the printing's `card_types`
            // (mirrors PumpTargetCreatureUntilEOT's filter).
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
            // Snapshot effective power at resolve time.
            //
            // **Round-53 §2 fix.** Was
            // `read_battlefield_creature_power` (the round-17 Fight
            // helper), which DELIBERATELY omits `obj.counters` (a
            // pinned combat-side asymmetry). Python's source-of-truth
            // `DoubleTargetCreaturesPowerUEOT.resolve` (`pump.py:234`)
            // snapshots `effective_power` = `_compute_effective_pt`,
            // which FOLDS IN +1/+1 counters (game.py:2251). On a
            // target with +1/+1 counters the two engines doubled
            // DIFFERENT values (Rust base, Python effective) — a real
            // §2 silent mistranslation, latent only because the
            // round-31/36 genuine Mightform probe staged a
            // counter-free creature. Now reads `read_doubling_power`
            // (base + ueot_power_bonus + obj.counters) so BOTH engines
            // double the SAME effective-power snapshot. Pinned by the
            // round-53 +1/+1-counter regression + cross-engine pins +
            // the extended genuine Mightform probe. Documented in
            // `docs/SEARCH_LIMITATIONS.md`.
            let snapshot = read_doubling_power(state, target_id);
            if snapshot <= 0 {
                return Ok(()); // ≤ 0 power → silent fizzle (no inversion)
            }
            // Push the snapshot as a UEOT power-only modifier.
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in zone.iter_mut() {
                if obj.id == target_id {
                    obj.ueot_modifiers.push(UeotModifier::PowerToughnessBonus {
                        power: snapshot,
                        toughness: 0,
                    });
                    break;
                }
            }
        }
        // BLOCKED-RUST-EFFECT slice (round 32). Deal damage to
        // target creature an opponent controls equal to the number
        // of artifacts the source's controller controls (Warmaker
        // Gunship's ETB; 1 EoE consumer). First dynamic-X-from-
        // permanent-count primitive in Rust.
        //
        // **Mechanism — count + apply.** Compute `amount` as the
        // number of permanents on the source-controller's bf whose
        // printing's `card_types` contains "Artifact" (matches
        // Python: lands that are also artifacts count, tokens like
        // Lander count). If amount ≤ 0 → silent fizzle (no targets
        // chosen, no damage). Otherwise route through the same
        // opponent-creature target shape as
        // `Effect::DealDamageToOpponentCreature`: scan opponents in
        // ascending player order, pick the first creature on each
        // opponent's bf, apply `amount` damage to it. No opponent
        // creature → silent fizzle.
        //
        // **Source-controller resolution.** Mirrors
        // `Effect::DealDamageToOpponentCreature` shape — 5-zone scan
        // + stack scan, falling through to silent fizzle if the
        // source isn't trackable (e.g. counterspelled). Distinct
        // from the I79 transient-slot lookup
        // (current_resolve_source_controller) used by
        // PumpTargetCreatureUntilEOT / DoubleTargetCreaturesPowerUEOT
        // because those arms target the source's OWN side and the
        // I79 slot is the canonical source-controller cache there.
        // For the `damage opponent` shape we already commit to the
        // 5-zone scan precedent set by DealDamageToOpponentCreature
        // for cross-arm consistency on this target shape.
        Effect::DealDamageToOpponentCreatureByArtifactCount => {
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors DealDamageToOpponentCreature shape).
            let mut source_controller: Option<u8> = None;
            'outer_sc: for player in state.players.iter() {
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
                            break 'outer_sc;
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
            // Count source-controller's artifacts on bf. Mirrors
            // Python's `sum(1 for o in state.battlefield if
            // o.controller_id == controller_id and
            // o.printing.is_artifact)` at damage.py:445-448.
            // Scryfall's card_types convention has "Artifact" in
            // the card_types list for any artifact (including
            // artifact-creatures, artifact-lands, tokens with
            // Artifact type).
            let cidx = controller as usize;
            let mut amount: i32 = 0;
            for obj in state.players[cidx].battlefield.iter() {
                let Some(printing) = state.registry.printings.get(obj.printing_id as usize)
                else {
                    continue;
                };
                if printing.card_types.iter().any(|t| t == "Artifact") {
                    amount = amount.saturating_add(1);
                }
            }
            if amount <= 0 {
                return Ok(()); // no artifacts → silent fizzle (matches Python damage.py:449-450)
            }
            // Pick first eligible target: scan opponents in
            // ascending order, pick the first Creature on each
            // opponent's bf. Mirrors DealDamageToOpponentCreature
            // target shape.
            let mut found: Option<(usize, u32)> = None;
            'outer_tg: for (pidx, player) in state.players.iter().enumerate() {
                if pidx as u8 == controller {
                    continue;
                }
                for obj in player.battlefield.iter() {
                    let Some(printing) =
                        state.registry.printings.get(obj.printing_id as usize)
                    else {
                        continue;
                    };
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        found = Some((pidx, obj.id));
                        break 'outer_tg;
                    }
                }
            }
            if let Some((pidx, target_id)) = found {
                let amount_i16 = amount.min(i16::MAX as i32) as i16;
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                        break;
                    }
                }
            }
            // else: no opponent creature → silent fizzle.
        }
        // BLOCKED-RUST-EFFECT slice (round 51) — Monoist
        // Circuit-Feeder ETB (real EoE card; 14,727 17lands decks).
        // Until EOT: the source-controller's FIRST creature gets
        // +X/+0; an opponent's FIRST creature gets -0/-X; X = the
        // source-controller's artifact count (clamped >= 0; X<=0 ->
        // silent no-op). Sister of round-32
        // DealDamageToOpponentCreatureByArtifactCount: SAME
        // source-controller resolution (5-zone + stack scan) and
        // SAME artifact-count denominator, NEW two-subject until-EOT
        // pump+debuff apply substrate (reuses the
        // PumpTargetCreatureUntilEOT UeotModifier::PowerToughnessBonus
        // push shape). Mirrors Python's deterministic-pick bridge
        // sibling PumpYoursAndDebuffOpponentByArtifactCountUntilEOT.
        //
        // **Per-side independence (CR 608.2c).** The oracle uses TWO
        // independent "target" clauses (NOT "up to one"); if one
        // side has no legal creature the ability still resolves the
        // half that does. So each side is applied independently:
        // missing source-side creature -> source-side no-op (opponent
        // side still applies) and vice-versa. Matches Python's
        // per-slot independent apply in
        // PumpYoursAndDebuffOpponentByArtifactCountUntilEOT.
        Effect::TwoSubjectPumpAndDebuffByArtifactCount => {
            // Source-controller resolution (5-zone walk + stack
            // scan; mirrors round-32 sister shape exactly).
            let mut source_controller: Option<u8> = None;
            'outer_sc_tspd: for player in state.players.iter() {
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
                            break 'outer_sc_tspd;
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
            // Artifact-count denominator on the source-controller's
            // bf. Mirrors round-32
            // DealDamageToOpponentCreatureByArtifactCount BIT-FOR-BIT
            // (Scryfall card_types has "Artifact" for any artifact,
            // including artifact-creatures / artifact-lands / tokens
            // with the Artifact type) and Python's
            // `CountControlledMatching(IsArtifact())` formula.
            let cidx = controller as usize;
            let mut x: i32 = 0;
            for obj in state.players[cidx].battlefield.iter() {
                let Some(printing) =
                    state.registry.printings.get(obj.printing_id as usize)
                else {
                    continue;
                };
                if printing.card_types.iter().any(|t| t == "Artifact") {
                    x = x.saturating_add(1);
                }
            }
            if x <= 0 {
                return Ok(()); // X <= 0 -> silent no-op
            }
            // Source-side target: FIRST creature on the
            // source-controller's bf (smallest Vec index). Same
            // deterministic scan FightTargetCreatureWithTargetCreature
            // / PumpTargetCreatureUntilEOT use.
            let own_target_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing =
                        registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            // Opponent-side target: FIRST creature on the opponent's
            // bf. 2-player engine = exactly one opponent at
            // 1 - controller.
            let opponent: u8 = 1 - controller;
            let oidx = opponent as usize;
            let opp_target_id: Option<u32> = {
                let bf = &state.players[oidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing =
                        registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            // Apply the source-side +X/+0 UEOT modifier (independent
            // of whether the opponent side has a target — CR 608.2c).
            if let Some(target_id) = own_target_id {
                let zone: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[cidx].battlefield);
                for obj in zone.iter_mut() {
                    if obj.id == target_id {
                        obj.ueot_modifiers.push(
                            UeotModifier::PowerToughnessBonus {
                                power: x,
                                toughness: 0,
                            },
                        );
                        break;
                    }
                }
            }
            // Apply the opponent-side +0/-X UEOT modifier
            // (independent of the source side).
            if let Some(target_id) = opp_target_id {
                let zone: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[oidx].battlefield);
                for obj in zone.iter_mut() {
                    if obj.id == target_id {
                        obj.ueot_modifiers.push(
                            UeotModifier::PowerToughnessBonus {
                                power: 0,
                                toughness: -x,
                            },
                        );
                        break;
                    }
                }
            }
            // else (either side): no eligible creature → that side
            // is a silent no-op; the other side still applied.
        }
        // BLOCKED-RUST-EFFECT slice (round 35) — deal damage to an
        // opponent's creature equal to the source-controller's hand
        // size. Sister of round-32's
        // DealDamageToOpponentCreatureByArtifactCount: same target
        // shape (first eligible Creature on an opponent's bf, scanned
        // in ascending player order), same fizzle semantics
        // (silent no-op when count <= 0 or no opponent creature),
        // same source-controller resolution (5-zone scan + stack
        // scan), NEW denominator (hand size in place of artifact
        // count). Mirrors Python's
        // `DealDamageToOpponentCreatureByCardsInHand`
        // (`damage.py:464` — Roaring Furnace's door trigger,
        // 1 EoE consumer).
        //
        // **Hand-size denominator.** `state.players[cidx].hand.len()`
        // BIT-FOR-BIT mirrors Python's
        // `len(state.player_by_id(controller_id).hand)` at
        // damage.py:511. The source itself is already on the
        // battlefield by the time the door / ETB trigger resolves
        // (it left the controller's hand on cast resolution), so the
        // hand-of-N + cast-source case produces N damage, not N+1 —
        // identical to Python.
        Effect::DealDamageToOpponentCreatureByCardsInHand => {
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors round-32 sister shape exactly).
            let mut source_controller: Option<u8> = None;
            'outer_sc_chnd: for player in state.players.iter() {
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
                            break 'outer_sc_chnd;
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
            // Read source-controller's hand size. Mirrors Python's
            // `hand_size = len(state.player_by_id(controller_id).hand)`
            // at damage.py:511. usize → i32 saturating cast (any
            // realistic hand fits in i32; defensive cap follows the
            // round-32 saturating-add denominator convention).
            let cidx = controller as usize;
            let hand_len = state.players[cidx].hand.len();
            let amount: i32 = if hand_len > i32::MAX as usize {
                i32::MAX
            } else {
                hand_len as i32
            };
            if amount <= 0 {
                return Ok(()); // empty hand → silent fizzle (matches Python damage.py:512-513)
            }
            // Pick first eligible target: scan opponents in ascending
            // order, pick the first Creature on each opponent's bf.
            // BIT-FOR-BIT mirror of the round-32 sister target shape.
            let mut found: Option<(usize, u32)> = None;
            'outer_tg_chnd: for (pidx, player) in state.players.iter().enumerate() {
                if pidx as u8 == controller {
                    continue;
                }
                for obj in player.battlefield.iter() {
                    let Some(printing) =
                        state.registry.printings.get(obj.printing_id as usize)
                    else {
                        continue;
                    };
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        found = Some((pidx, obj.id));
                        break 'outer_tg_chnd;
                    }
                }
            }
            if let Some((pidx, target_id)) = found {
                let amount_i16 = amount.min(i16::MAX as i32) as i16;
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                        break;
                    }
                }
            }
            // else: no opponent creature → silent fizzle.
        }
        // BLOCKED-RUST-EFFECT slice (round 36) — deal damage to an
        // opponent's creature equal to the source-controller's lands
        // count. Sister of round-32's
        // DealDamageToOpponentCreatureByArtifactCount and round-35's
        // DealDamageToOpponentCreatureByCardsInHand: same target shape
        // (first eligible Creature on an opponent's bf, scanned in
        // ascending player order), same fizzle semantics (silent
        // no-op when count <= 0 or no opponent creature), same
        // source-controller resolution (5-zone scan + stack scan),
        // NEW denominator (lands-controlled in place of artifact-count
        // / hand-size). Mirrors Python's
        // `DealDamageToOpponentCreatureByLandsControlled`
        // (shipped in this slice; 0 EoE consumers today, slice ships
        // per round-27/31 round-trip-surface-coverage rule and to
        // complete the THIRD orthogonal denominator on the round-32
        // damage-to-opponent-creature substrate).
        //
        // **Lands denominator.** Walk the source-controller's bf
        // once; for each obj, count +1 if `printing.card_types`
        // contains "Land". Mirrors the round-32 artifact-count
        // walking pattern BIT-FOR-BIT with "Artifact" replaced by
        // "Land" -- and matches Python's
        // `sum(1 for o in state.battlefield if o.controller_id ==
        // controller_id and o.printing.is_land)` denominator shape.
        // Dual-typed artifact-lands carry BOTH "Land" and "Artifact"
        // in card_types -- they count for both the artifact-count
        // and the lands-controlled denominators independently
        // (mirrors Scryfall typeline conventions and Python's
        // `is_land` / `is_artifact` disjunction at the printing
        // level).
        Effect::DealDamageToOpponentCreatureByLandsControlled => {
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors round-32 / round-35 sister shape exactly).
            let mut source_controller: Option<u8> = None;
            'outer_sc_clnd: for player in state.players.iter() {
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
                            break 'outer_sc_clnd;
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
            // Count source-controller's lands on bf. Mirrors Python's
            // `sum(1 for o in state.battlefield if o.controller_id ==
            // controller_id and o.printing.is_land)` shape. Walks the
            // round-32 artifact-count loop BIT-FOR-BIT with the type
            // string replaced.
            let cidx = controller as usize;
            let mut amount: i32 = 0;
            for obj in state.players[cidx].battlefield.iter() {
                let Some(printing) = state.registry.printings.get(obj.printing_id as usize)
                else {
                    continue;
                };
                if printing.card_types.iter().any(|t| t == "Land") {
                    amount = amount.saturating_add(1);
                }
            }
            if amount <= 0 {
                return Ok(()); // no lands → silent fizzle (matches Python's `if lands_count <= 0: return`)
            }
            // Pick first eligible target: scan opponents in
            // ascending order, pick the first Creature on each
            // opponent's bf. BIT-FOR-BIT mirror of the round-32 /
            // round-35 sister target shape.
            let mut found: Option<(usize, u32)> = None;
            'outer_tg_clnd: for (pidx, player) in state.players.iter().enumerate() {
                if pidx as u8 == controller {
                    continue;
                }
                for obj in player.battlefield.iter() {
                    let Some(printing) =
                        state.registry.printings.get(obj.printing_id as usize)
                    else {
                        continue;
                    };
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        found = Some((pidx, obj.id));
                        break 'outer_tg_clnd;
                    }
                }
            }
            if let Some((pidx, target_id)) = found {
                let amount_i16 = amount.min(i16::MAX as i32) as i16;
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                        break;
                    }
                }
            }
            // else: no opponent creature → silent fizzle.
        }
        // BLOCKED-RUST-EFFECT slice (round 37) -- deal damage to an
        // opponent's creature equal to the source-controller's
        // creatures count. Sister of round-32's
        // DealDamageToOpponentCreatureByArtifactCount, round-35's
        // DealDamageToOpponentCreatureByCardsInHand, and round-36's
        // DealDamageToOpponentCreatureByLandsControlled: same target
        // shape (first eligible Creature on an opponent's bf, scanned
        // in ascending player order), same fizzle semantics (silent
        // no-op when count <= 0 or no opponent creature), same
        // source-controller resolution (5-zone scan + stack scan),
        // NEW denominator (creatures-controlled in place of artifact
        // count / hand-size / lands-controlled). Mirrors Python's
        // `DealDamageToOpponentCreatureByCreaturesYouControl`
        // (shipped in this slice; 0 EoE consumers today, slice ships
        // per round-27/31 round-trip-surface-coverage rule and to
        // complete the FOURTH orthogonal denominator on the round-32
        // damage-to-opponent-creature substrate).
        //
        // **Creatures denominator.** Walk the source-controller's bf
        // once; for each obj, count +1 if `printing.card_types`
        // contains "Creature". Mirrors the round-32 artifact-count
        // walking pattern BIT-FOR-BIT with "Artifact" replaced by
        // "Creature" -- and matches Python's
        // `sum(1 for o in state.battlefield if o.controller_id ==
        // controller_id and o.printing.is_creature)` denominator
        // shape. The source itself counts toward the denominator if it
        // is a Creature still on the source-controller's bf at resolve
        // time (mirrors Python's vanilla walk over state.battlefield
        // -- no source-exclusion clause). Dual-typed artifact-
        // creatures carry BOTH "Creature" and "Artifact" in card_types
        // -- they count for both the artifact-count and the
        // creatures-controlled denominators independently (mirrors
        // Scryfall typeline conventions and Python's `is_artifact` /
        // `is_creature` disjunction at the printing level).
        Effect::DealDamageToOpponentCreatureByCreaturesYouControl => {
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors round-32 / round-35 / round-36 sister shape
            // exactly).
            let mut source_controller: Option<u8> = None;
            'outer_sc_cyc: for player in state.players.iter() {
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
                            break 'outer_sc_cyc;
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
            // Count source-controller's creatures on bf. Mirrors
            // Python's `sum(1 for o in state.battlefield if
            // o.controller_id == controller_id and
            // o.printing.is_creature)` shape. Walks the round-32
            // artifact-count loop BIT-FOR-BIT with the type string
            // replaced.
            let cidx = controller as usize;
            let mut amount: i32 = 0;
            for obj in state.players[cidx].battlefield.iter() {
                let Some(printing) = state.registry.printings.get(obj.printing_id as usize)
                else {
                    continue;
                };
                if printing.card_types.iter().any(|t| t == "Creature") {
                    amount = amount.saturating_add(1);
                }
            }
            if amount <= 0 {
                return Ok(()); // no creatures → silent fizzle (matches Python's `if creatures_count <= 0: return`)
            }
            // Pick first eligible target: scan opponents in ascending
            // order, pick the first Creature on each opponent's bf.
            // BIT-FOR-BIT mirror of the round-32 / round-35 / round-36
            // sister target shape.
            let mut found: Option<(usize, u32)> = None;
            'outer_tg_cyc: for (pidx, player) in state.players.iter().enumerate() {
                if pidx as u8 == controller {
                    continue;
                }
                for obj in player.battlefield.iter() {
                    let Some(printing) =
                        state.registry.printings.get(obj.printing_id as usize)
                    else {
                        continue;
                    };
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        found = Some((pidx, obj.id));
                        break 'outer_tg_cyc;
                    }
                }
            }
            if let Some((pidx, target_id)) = found {
                let amount_i16 = amount.min(i16::MAX as i32) as i16;
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                        break;
                    }
                }
            }
            // else: no opponent creature → silent fizzle.
        }
        // BLOCKED-RUST-EFFECT slice (round 46) -- deal damage to an
        // opponent's creature equal to the source-controller's
        // graveyard size. Sister of round-32's
        // DealDamageToOpponentCreatureByArtifactCount, round-35's
        // DealDamageToOpponentCreatureByCardsInHand, round-36's
        // DealDamageToOpponentCreatureByLandsControlled, and round-37's
        // DealDamageToOpponentCreatureByCreaturesYouControl: same
        // target shape (first eligible Creature on an opponent's bf,
        // scanned in ascending player order), same fizzle semantics
        // (silent no-op when count <= 0 or no opponent creature), same
        // source-controller resolution (5-zone scan + stack scan), NEW
        // denominator (graveyard size in place of artifact-count /
        // hand-size / lands-controlled / creatures-controlled).
        // Mirrors Python's
        // `DealDamageToOpponentCreatureByCardsInGraveyard`
        // (`damage.py` -- shipped in this slice; no pre-existing
        // class). FIFTH denominator on the damage substrate; SIXTH
        // overall X-from-count denominator across the substrate matrix
        // (prior five: artifact-count / hand-size / lands-controlled /
        // creatures-controlled / life-total). FIRST zone-size
        // denominator pulled from a non-battlefield, non-hand source.
        //
        // **Graveyard-size denominator.**
        // `state.players[cidx].graveyard.len()` BIT-FOR-BIT mirrors
        // Python's `len(state.player_by_id(controller_id).graveyard)`
        // shape. Mirrors the round-35 hand-size denominator's
        // `state.players[cidx].hand.len()` shape exactly with `hand`
        // swapped for `graveyard`. The source itself is on the
        // battlefield at resolve time for an ETB-style trigger -- it
        // does NOT contribute to the denominator (not in graveyard
        // yet). For an LTB-style or graveyard-resolve trigger where
        // the source has moved to the graveyard before this arm runs,
        // the source WOULD count by virtue of the move (no source-
        // exclusion clause -- mirrors round-32 / round-35 / round-36 /
        // round-37 sister convention).
        Effect::DealDamageToOpponentCreatureByCardsInGraveyard => {
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors round-32 / round-35 / round-36 / round-37 sister
            // shape exactly).
            let mut source_controller: Option<u8> = None;
            'outer_sc_cgv: for player in state.players.iter() {
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
                            break 'outer_sc_cgv;
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
            // Read source-controller's graveyard size. Mirrors
            // Python's
            // `gy_size = len(state.player_by_id(controller_id).graveyard)`
            // shape. usize -> i32 saturating cast (any realistic
            // graveyard fits in i32; defensive cap follows the
            // round-32 saturating-add denominator convention).
            let cidx = controller as usize;
            let gy_len = state.players[cidx].graveyard.len();
            let amount: i32 = if gy_len > i32::MAX as usize {
                i32::MAX
            } else {
                gy_len as i32
            };
            if amount <= 0 {
                return Ok(()); // empty graveyard → silent fizzle (matches Python's `if gy_size <= 0: return`)
            }
            // Pick first eligible target: scan opponents in ascending
            // order, pick the first Creature on each opponent's bf.
            // BIT-FOR-BIT mirror of the round-32 / round-35 / round-36
            // / round-37 sister target shape.
            let mut found: Option<(usize, u32)> = None;
            'outer_tg_cgv: for (pidx, player) in state.players.iter().enumerate() {
                if pidx as u8 == controller {
                    continue;
                }
                for obj in player.battlefield.iter() {
                    let Some(printing) =
                        state.registry.printings.get(obj.printing_id as usize)
                    else {
                        continue;
                    };
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        found = Some((pidx, obj.id));
                        break 'outer_tg_cgv;
                    }
                }
            }
            if let Some((pidx, target_id)) = found {
                let amount_i16 = amount.min(i16::MAX as i32) as i16;
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                        break;
                    }
                }
            }
            // else: no opponent creature → silent fizzle.
        }
        // BLOCKED-RUST-EFFECT slice (round 47) -- deal damage to an
        // opponent's creature equal to the source-controller's LIFE
        // TOTAL. Sister of round-32's
        // DealDamageToOpponentCreatureByArtifactCount, round-35's
        // DealDamageToOpponentCreatureByCardsInHand, round-36's
        // DealDamageToOpponentCreatureByLandsControlled, round-37's
        // DealDamageToOpponentCreatureByCreaturesYouControl, and
        // round-46's DealDamageToOpponentCreatureByCardsInGraveyard:
        // same target shape (first eligible Creature on an opponent's
        // bf, scanned in ascending player order), same fizzle
        // semantics (silent no-op when count <= 0 or no opponent
        // creature), same source-controller resolution (5-zone scan +
        // stack scan), NEW denominator (clamped life total in place of
        // artifact-count / hand-size / lands-controlled /
        // creatures-controlled / graveyard-size). Mirrors Python's
        // `DealDamageToOpponentCreatureByLifeTotal` (`damage.py` --
        // shipped in this slice; no pre-existing class). SIXTH (final)
        // denominator on the damage substrate -- the damage substrate
        // row of the X-from-count matrix is now fully saturated across
        // the artifact / hand / lands / creatures / graveyard /
        // life-total denominator axis.
        //
        // **Life-total denominator.** `state.players[cidx].life` is
        // i32; `life.max(0)` clamps negative life totals (arbitrary
        // lose-life-past-zero / infect-style scenarios; an SBA would
        // normally have ended the game) to zero -- silent no-op,
        // BIT-FOR-BIT matching Python's
        // `max(0, state.player_by_id(controller_id).life)` clamp and
        // the round-42 `MillTargetPlayerEqualToYourLifeTotal`
        // `life.max(0)` precedent at state_ops_resolve.rs:1276. The
        // life total is read from the source-controller (the player
        // whose creature/spell is the effect source), NOT the target
        // -- a "deals damage equal to your life total" effect reads
        // *your* (controller's) life.
        Effect::DealDamageToOpponentCreatureByLifeTotal => {
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors round-32 / round-35 / round-36 / round-37 /
            // round-46 sister shape exactly).
            let mut source_controller: Option<u8> = None;
            'outer_sc_lft: for player in state.players.iter() {
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
                            break 'outer_sc_lft;
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
            // Read source-controller's life total and clamp negative
            // life to 0. Mirrors Python's
            // `n = max(0, state.player_by_id(controller_id).life)`
            // shape (round-42 mill `life.max(0)` precedent).
            let cidx = controller as usize;
            let life = state.players[cidx].life;
            let amount: i32 = life.max(0);
            if amount <= 0 {
                return Ok(()); // life <= 0 → silent fizzle (matches Python's `if life_total <= 0: return`)
            }
            // Pick first eligible target: scan opponents in ascending
            // order, pick the first Creature on each opponent's bf.
            // BIT-FOR-BIT mirror of the round-32 / round-35 / round-36
            // / round-37 / round-46 sister target shape.
            let mut found: Option<(usize, u32)> = None;
            'outer_tg_lft: for (pidx, player) in state.players.iter().enumerate() {
                if pidx as u8 == controller {
                    continue;
                }
                for obj in player.battlefield.iter() {
                    let Some(printing) =
                        state.registry.printings.get(obj.printing_id as usize)
                    else {
                        continue;
                    };
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        found = Some((pidx, obj.id));
                        break 'outer_tg_lft;
                    }
                }
            }
            if let Some((pidx, target_id)) = found {
                let amount_i16 = amount.min(i16::MAX as i32) as i16;
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                        break;
                    }
                }
            }
            // else: no opponent creature → silent fizzle.
        }
        // BLOCKED-RUST-EFFECT slice (round 33) — put a +1/+1 counter
        // on the source for each OTHER creature and/or artifact the
        // source's controller controls. Mirrors Python's
        // `PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact`
        // (`counters.py:394` — Luxknight Breacher's ETB).
        //
        // **Source-controller resolution.** Battlefield-only scan
        // (mirrors round-23 `PutPlusOneCounterOnSelf` shape). A
        // "+1/+1 counter on this creature" effect requires the source
        // to be on a battlefield zone; if it's gone (counterspelled,
        // bounced, etc.), silent fizzle.
        //
        // **Other-creature-or-artifact count.** Walk the source-
        // controller's battlefield once; for each obj other than the
        // source itself, count +1 if `printing.card_types` contains
        // "Creature" OR "Artifact". Artifact-creatures count once
        // (the disjunction short-circuits — same semantics as
        // Python's `is_creature or is_artifact`).
        //
        // **Apply.** If count > 0, add `count` to the source's
        // `counters` field via `saturating_add` on the
        // `Arc::make_mut`-borrowed bf vec. Mirrors the round-23
        // `PutPlusOneCounterOnSelf` mutation pattern bit-for-bit.
        //
        // **Fizzle paths.** Source not on bf → silent fizzle. Count
        // ≤ 0 (only the source on the controller's bf) → silent
        // fizzle (matches Python's `if count <= 0: return`).
        Effect::PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact => {
            // Locate the source on a battlefield zone (round-23
            // PutPlusOneCounterOnSelf shape).
            let mut found_player: Option<usize> = None;
            for (pidx, player) in state.players.iter().enumerate() {
                if player.battlefield.iter().any(|o| o.id == source_obj_id) {
                    found_player = Some(pidx);
                    break;
                }
            }
            let pidx = match found_player {
                Some(p) => p,
                None => return Ok(()), // source not on bf → silent fizzle
            };
            // Count source-controller's other creatures+artifacts.
            // Mirrors Python's `for o in state.battlefield: if
            // o.id == source.id: continue; if o.controller_id !=
            // controller_id: continue; if o.printing.is_creature or
            // o.printing.is_artifact: count += 1` at counters.py:411-418.
            let mut count: i32 = 0;
            for obj in state.players[pidx].battlefield.iter() {
                if obj.id == source_obj_id {
                    continue;
                }
                let Some(printing) = state.registry.printings.get(obj.printing_id as usize)
                else {
                    continue;
                };
                let is_creature_or_artifact = printing
                    .card_types
                    .iter()
                    .any(|t| t == "Creature" || t == "Artifact");
                if is_creature_or_artifact {
                    count = count.saturating_add(1);
                }
            }
            if count <= 0 {
                return Ok(()); // no other creatures/artifacts → silent fizzle
            }
            // Apply: add `count` +1/+1 counters to source. Mirrors
            // round-23 PutPlusOneCounterOnSelf mutation pattern.
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == source_obj_id {
                    obj.counters = obj.counters.saturating_add(count);
                    break;
                }
            }
        }
        // BLOCKED-RUST-EFFECT slice (round 34) — surveil X, where X is
        // the source-controller's artifact count. Sister of round-32
        // DealDamageToOpponentCreatureByArtifactCount (same X-from-
        // artifact-count denominator) and round-15 Effect::Surveil
        // (same SurveilChoice PendingDecision shape). Resolves to a
        // SurveilChoice carrying min(artifact_count, library_len)
        // cards off the controller's library top, with the controller
        // resolved via I61 transient slot first then 5-zone+stack
        // scan fallback.
        Effect::SurveilXEqualToArtifactCount => {
            // Source-controller resolution — try I61 transient slot
            // first (mirrors round-15 Effect::Surveil), then fall back
            // to 5-zone scan + stack scan (mirrors round-32
            // DealDamageToOpponentCreatureByArtifactCount robustness).
            let mut source_controller: Option<u8> =
                state.current_resolve_source_controller;
            if source_controller.is_none() {
                'outer_sc: for player in state.players.iter() {
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
                                break 'outer_sc;
                            }
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
            // Final fallback: active_player. Preserves the "always
            // emit exactly one PendingDecision" contract that auto-
            // resolve depends on (mirrors round-15 Effect::Surveil's
            // unconditional push at state_ops_resolve.rs:2726-2730).
            let controller = source_controller.unwrap_or(state.active_player);
            let cidx = controller as usize;
            // Count source-controller's artifacts on bf. BIT-FOR-BIT
            // mirror of round-32's DealDamageToOpponentCreatureByArtifactCount
            // counting denominator at state_ops_resolve.rs:4550-4560.
            let mut count: i32 = 0;
            for obj in state.players[cidx].battlefield.iter() {
                let Some(printing) = state.registry.printings.get(obj.printing_id as usize)
                else {
                    continue;
                };
                if printing.card_types.iter().any(|t| t == "Artifact") {
                    count = count.saturating_add(1);
                }
            }
            // Pop min(count, library_len) cards off library TOP into
            // a SurveilChoice PendingDecision. IDENTICAL post-pop
            // state shape to round-15 Effect::Surveil resolve arm at
            // state_ops_resolve.rs:2705-2730. count == 0 (controller
            // has zero artifacts) is a legitimate no-op surveil — we
            // still push an empty SurveilChoice so the auto-resolve
            // invariant (every Surveil emits exactly one
            // PendingDecision) holds; auto-resolve discards it in
            // O(1) (matches round-15 count = 0 comment).
            let lib_len = state.players[cidx].library.len();
            let n = (count.max(0) as usize).min(lib_len);
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(n);
            for _ in 0..n {
                // Always remove index 0 — the new top after each prior
                // remove shifts down. Mirrors round-15 Surveil's
                // identical pop loop.
                let removed = lib_mut.remove(0);
                cards.push(removed);
            }
            state.pending_decisions.push(PendingDecision::SurveilChoice {
                source_obj_id,
                controller,
                cards,
            });
        }
        // BLOCKED-RUST-EFFECT slice — Fight effect arm. "Target
        // creature you control fights target creature an opponent
        // controls" (CR 701.12). Both fighters deal damage equal to
        // their power to the other simultaneously; per CR 701.12c, if
        // either fighter has left the battlefield by resolve time, no
        // damage is dealt at all.
        //
        // Mirrors the Pump-Target-Creature target-pick shape: scan
        // the source controller's bf for the FIRST creature (caster-
        // side fighter), and the OPPONENT's bf for the FIRST creature
        // (opponent-side fighter). Both creature-eligibility checks
        // gate on `card_types contains "Creature"`.
        //
        // Cross-controller routing: source-controller is resolved by
        // scanning every zone for `source_obj_id` (mirrors
        // PumpTargetCreatureUntilEOT's source-controller lookup). If
        // the source is untrackable (already gone from every zone —
        // e.g. counterspelled?) it's a silent fizzle.
        //
        // Damage-application: compute BOTH effective-power values
        // BEFORE applying any damage so the simultaneous-exchange
        // semantics hold (CR 701.12 — a fighter that takes lethal
        // still deals its damage). Skip the per-side write when the
        // attacker's power is 0 or negative (negative power doesn't
        // heal in MTG; the printed-power 0 case fires no damage
        // marker change either way, but `deal_damage` would have
        // raised on a negative argument so we explicitly clamp to
        // skip the call). SBAs are NOT triggered inline by this
        // arm; they fire on the next SBA pass after the resolve, by
        // which time both damage markers are in place.
        Effect::FightTargetCreatureWithTargetCreature => {
            // Source-controller resolution — scan every zone for the
            // source object. Same shape as PumpTargetCreatureUntilEOT.
            // Untrackable source = silent fizzle (mirrors the pump
            // arm's behavior).
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
            let opponent: u8 = 1 - controller;

            // Pick the first creature on the source-controller's bf
            // (the caster-side fighter). Mirrors
            // PumpTargetCreatureUntilEOT's same-side scan.
            let cidx = controller as usize;
            let oidx = opponent as usize;
            let registry = &state.registry;
            let caster_fighter_id: Option<u32> = state.players[cidx]
                .battlefield
                .iter()
                .find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                });
            // Pick the first creature on the OPPONENT's bf (the
            // opponent-side fighter). Mirrors DealDamageAnyTarget's
            // defender-side scan but creature-only (no fall-back to
            // damaging the player — fight is creature-vs-creature).
            let opponent_fighter_id: Option<u32> = state.players[oidx]
                .battlefield
                .iter()
                .find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                });
            // CR 701.12c: if either fighter is missing at resolve
            // time, the fight does NOT deal damage on either side.
            // Silent fizzle (mirrors the pump arm's no-target
            // behavior).
            let (Some(a_id), Some(b_id)) = (caster_fighter_id, opponent_fighter_id) else {
                return Ok(());
            };

            // Compute BOTH effective-power values BEFORE applying
            // any damage (CR 701.12 simultaneous-damage event).
            // Use the public `effective_power` getter shape
            // (state_ops_combat.rs:516) which returns the
            // printed-power + UEOT modifier sum, saturating into
            // i16. None for non-creatures or unknown ids — treat
            // as 0 defensively (the creature-filter scan above
            // should make this unreachable).
            let a_power = read_battlefield_creature_power(state, a_id);
            let b_power = read_battlefield_creature_power(state, b_id);

            // Apply both damages. `deal_damage` is the per-instance
            // damage-marker primitive (state_ops_damage.rs:196). It
            // raises on negative amount per the project's "fail
            // loud" convention, so explicitly clamp to >=0 (negative
            // power doesn't heal in MTG — it just deals 0 damage).
            // The two damages are independent: a fighter that
            // takes lethal in this exchange still dealt its damage
            // first because we read both powers BEFORE either
            // deal_damage call.
            if a_power > 0 {
                apply_damage_marker(state, b_id, a_power);
            }
            if b_power > 0 {
                apply_damage_marker(state, a_id, b_power);
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
        //
        // **Round-36 fix (Sequence(Surveil, DrawCards) ordering)**:
        // After each leaf effect resolves, drain any PendingDecisions
        // it pushed via the default "keep_all_on_top" auto-resolve
        // strategy BEFORE running the next leaf effect. This matches
        // Python's no-agent flow where Surveil's resolve never mutates
        // the library, so a following DrawCards-N draws from the
        // pre-Surveil top. Without this drain, Rust's
        // SurveilXEqualToArtifactCount (and any sister arm that pushes
        // a PendingDecision) leaves cards popped off the library top;
        // the next leaf (e.g. DrawCards-3 in Cerebral Download) then
        // reads the post-pop top and draws DIFFERENT cards than Python.
        // The terminal `auto_resolve_pending` call at
        // `resolve_top_of_stack` (line ~8533) re-inserts the surveiled
        // cards AFTER the entire spell loop, which is too late for the
        // intra-Sequence ordering. Driving the drain inside the loop
        // restores cross-engine parity for Cerebral Download
        // (Sequence(Surveil(use_artifact_count=True), DrawCards(3)))
        // and any future Sequence-of-pending-then-zone-reading shape.
        // See `docs/SEARCH_LIMITATIONS.md` "Sequence(Surveil,
        // DrawCards) PendingDecision-vs-inline ordering".
        Effect::Sequence { effects } => {
            for child in effects {
                apply_effect(state, child, source_obj_id)?;
                auto_resolve_pending(state, "keep_all_on_top")?;
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
        // **Tier-C target-seating sub-substrate (lever-a, Sunset
        // Saboteur).** Put `amount` +1/+1 counter(s) on a target
        // creature an OPPONENT of the source's controller controls.
        // Mirrors Python's `PutPlusOneCounterOnOpponentsCreature`
        // (a `PutPlusOneCounters` subclass; resolve walks its single
        // `TargetSpec(IsCreature() & ControlledByOpponent())` slot,
        // re-checks legality per CR 608.2b, and adds `amount` via
        // `add_plus_one_counters`).
        //
        // **Payload-target convention (NOT a self-scan).** Unlike the
        // you-control sibling arm above (which deterministically scans
        // the source-controller's own bf at apply time), this arm
        // reads the push-time-seated target from
        // `state.current_resolve_payload_target_id` exactly like
        // `Effect::EquipToTargetCreatureYouControl`. The seat is
        // computed by `first_legal_trigger_target` at
        // `push_triggered_ability` time (the Tier-C shared-seat
        // micro-substrate) so BOTH engines pick the SAME object: the
        // deterministic smallest-bf-index creature an opponent of the
        // source's controller controls. The CR 608.2b resolve-time
        // re-legality check (target still on a bf, still a creature,
        // still opponent-controlled) silently fizzles a target that
        // left the bf / changed control between push and resolve,
        // byte-equal with Python's
        // `PutPlusOneCounters.resolve`/`_slot_target_still_legal`
        // re-check. `amount=0` short-circuits; negative raises
        // (defense-in-depth — parse catches it at register time).
        Effect::PutPlusOneCounterOnOpponentsCreature { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "PutPlusOneCounterOnOpponentsCreature amount must be non-negative, got {amount}"
                )));
            }
            if *amount == 0 {
                return Ok(());
            }
            // Locate the source's controller (the same five-zone walk
            // + stack fallback the you-control sibling arm uses).
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
                return Ok(()); // source untracked → silent fizzle
            };
            // CR 608.2b resolve-time re-legality: the seated target
            // must still be on SOME player's bf, be a Creature, and be
            // controlled by an OPPONENT of `controller`. An unseeded
            // payload (no `first_legal_trigger_target` ran, e.g. a
            // direct `apply_effect_pub` caller) → silent fizzle, the
            // same observable as Python's no-target no-op (the seat is
            // the production path; this is defense-in-depth, mirrors
            // the EquipToTargetCreatureYouControl `None` fall-through
            // but WITHOUT a first-eligible self-scan — a self-scan
            // here is exactly the cross-engine divergence the shared
            // seat eliminates).
            let payload_target = match state.current_resolve_payload_target_id {
                Some(t) => t,
                None => return Ok(()),
            };
            let mut tgt_loc: Option<usize> = None;
            for (pidx, player) in state.players.iter().enumerate() {
                if let Some(obj) =
                    player.battlefield.iter().find(|o| o.id == payload_target)
                {
                    // Opponent-controlled (controller of the obj is not
                    // the source's controller) AND a creature.
                    if obj.controller == controller {
                        return Ok(()); // became own creature → fizzle
                    }
                    let printing = match state
                        .registry
                        .printings
                        .get(obj.printing_id as usize)
                    {
                        Some(p) => p,
                        None => return Ok(()),
                    };
                    if !printing.card_types.iter().any(|t| t == "Creature") {
                        return Ok(()); // no longer a creature → fizzle
                    }
                    tgt_loc = Some(pidx);
                    break;
                }
            }
            let Some(tidx) = tgt_loc else {
                return Ok(()); // target left the bf → silent fizzle
            };
            let delta = *amount;
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[tidx].battlefield);
            for obj in zone.iter_mut() {
                if obj.id == payload_target {
                    obj.counters = obj.counters.saturating_add(delta);
                    break;
                }
            }
        }
        // **Tier-C target-seating sub-substrate (lever-a, Exosuit
        // Savior — the count_min=0 optional-bounce edge).** Return
        // the push-time-SEATED target permanent (the source's
        // controller's own non-source non-player permanent) to its
        // owner's hand. Mirrors Python's
        // `ReturnTargetPermanentYouControlToOwnersHand` (a `Bounce`
        // subclass; `Bounce.resolve` no-ops on empty `targets` — the
        // optional decline).
        //
        // **The count_min=0 optional edge.** No seat
        // (`current_resolve_payload_target_id` is `None` — the
        // shared seat returned `None` because no eligible own
        // permanent existed, so `push_triggered_ability` pushed via
        // the unchanged `new_trigger` path) ⇒ silent no-op, byte
        // equal with Python's `targets=()` `Bounce.resolve`
        // early-`return`. NOT a fizzle-skip-push (that is Sunset
        // Saboteur's count_min>=1 semantics).
        //
        // **Payload-target convention + CR 608.2b.** When seated,
        // re-validate at resolve: the target must still be on the
        // source's controller's battlefield, not be the source, and
        // be a permanent (it always is — players are excluded by the
        // seat filter; the re-check is defense-in-depth + the
        // left-bf / changed-control fizzle). Bounce lifecycle mirrors
        // the `Effect::ReturnToHand` AnyCreature arm: zone→HAND,
        // reset damage/counters/attach, mark left-bf-if-nonland, LTB
        // fan-out via `pending_leaves_dispatches` + the round-55
        // token-cease sibling.
        Effect::ReturnTargetPermanentYouControlToOwnersHand => {
            // Locate the source's controller (the same five-zone walk
            // + stack fallback the counter arms use).
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
                return Ok(()); // source untracked → silent fizzle
            };
            // count_min=0 optional: no seat → no-op (the optional was
            // declined; byte-equal with Python's targets=() no-op).
            let payload_target = match state.current_resolve_payload_target_id {
                Some(t) => t,
                None => return Ok(()),
            };
            // CR 608.2b resolve-time re-legality: still on the
            // source-controller's bf, not the source itself. (Players
            // are never seated — the filter excludes them — but the
            // not-source guard mirrors Python's ~IsSource() slot.)
            let cidx = controller as usize;
            let pos = match state.players[cidx]
                .battlefield
                .iter()
                .position(|o| o.id == payload_target && o.id != source_obj_id)
            {
                Some(p) => p,
                None => return Ok(()), // left bf / became illegal → fizzle
            };
            // Bounce lifecycle — mirrors the Effect::ReturnToHand
            // AnyCreature arm (the established bounce-to-hand shape).
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            let mut obj = bf_mut.remove(pos);
            obj.zone = ZONE_HAND;
            obj.tapped = false;
            // CE13: summoning_sick NOT reset (Python's
            // move_off_battlefield omits it; re-ETB restamps it).
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
            // Owner == the source's controller (Exosuit Savior bounces
            // a permanent ITS controller controls; controller == owner
            // for the EoE consumer — same owner/controller convention
            // as the ReturnToHand first-slice arm).
            Arc::make_mut(&mut state.players[cidx].hand).push(obj);
            // Round-29 Void LTB tracking: bounce is a battlefield-exit;
            // flag flips iff the bounced object is nonland.
            mark_left_battlefield_if_nonland(state, printing_id);
            // LTB fan-out + round-55 token-cease sibling — queued for
            // the post-pop drain in resolve_top_of_stack (identical to
            // the ReturnToHand arm).
            state.pending_leaves_dispatches.push(leaving_obj_id);
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
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
        // (G19), may_fail interactive choice (no decision callback yet
        // for "decline fetch").
        //
        // **Round-30 supertypes/subtypes substrate.** The
        // `legendary_creature` / `spacecraft` / `sliver` / `demon`
        // filters that Round-21 documented as silent-fizzling are now
        // dispatched off the new `supertypes` field
        // (cards.rs:`CardPrinting.supertypes`) and the existing
        // `subtypes` field. Mirrors Python's `SearchLibraryForCard.
        // _matches` at `src/mtg_bot/effects/generic/search.py:48-81`
        // arm-for-arm. Unknown filter still silent-fizzles via the
        // `_ => false` fallthrough (matches Python's terminal `return
        // False`).
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
            // Top-to-bottom scan via forward iter (post-CE3: lib[0]
            // is top).
            let max_mv_local = *max_mv;
            let pos: Option<usize> = {
                let lib = &state.players[cidx].library;
                let registry = &state.registry;
                let mut found: Option<usize> = None;
                for (i, obj) in lib.iter().enumerate() {
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
                        // Round-30 supertypes-substrate dispatch. Legendary
                        // creature card: type line carries both "Legendary"
                        // (supertype) and "Creature" (card type). Mirrors
                        // Python's `printing.is_creature and "Legendary" in
                        // printing.supertypes` at search.py:50-53.
                        "legendary_creature" => {
                            printing.card_types.iter().any(|t| t == "Creature")
                                && printing.supertypes.iter().any(|s| s == "Legendary")
                        }
                        // Round-30 subtypes-keyed dispatch. Spacecraft is a
                        // subtype (CR 205.3p). Mirrors Python's
                        // `printing.is_spacecraft` at search.py:70-71 which
                        // reads `"Spacecraft" in printing.subtypes`. Note
                        // we DON'T also gate on `card_types contains
                        // "Artifact"` — Spacecraft printings carry the
                        // Artifact card type today, but the filter mirrors
                        // Python's pure-subtype check so a hypothetical
                        // non-Artifact Spacecraft (off-set fixture, future
                        // type-changing effect) still matches.
                        "spacecraft" => {
                            printing.subtypes.iter().any(|s| s == "Spacecraft")
                        }
                        // Round-30 subtypes-keyed dispatch. Sliver is a
                        // creature subtype. Mirrors Python's
                        // `"Sliver" in printing.subtypes` at search.py:72-73
                        // (no creature-card-type gate on the Python side
                        // either — the subtype implies the creature type
                        // for any well-formed printing, and the bridge
                        // mirrors that contract bit-for-bit).
                        "sliver" => {
                            printing.subtypes.iter().any(|s| s == "Sliver")
                        }
                        // Round-30 subtypes-keyed dispatch. Demon is a
                        // creature subtype (Demonic Counsel from Duskmourn).
                        // Mirrors Python's `"Demon" in printing.subtypes`
                        // at search.py:79-80.
                        "demon" => {
                            printing.subtypes.iter().any(|s| s == "Demon")
                        }
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
        // Mouth-of-the-Storm sibling — extended-duration debuff
        // anthem ("until your next turn"). First-slice resolve
        // semantics are IDENTICAL to the bare-EOT sibling above:
        // same source-controller lookup (5-zone walk + stack
        // fallback); same opponent-bf creature scan; same
        // `UeotModifier::PowerToughnessBonus` push. The cleanup-
        // gate divergence (Python keeps the modifier into the
        // opponent's turn, Rust drops it at the casting-turn
        // cleanup) is a deferred follow-up Rust slice — see
        // SEARCH_LIMITATIONS.md and the doc-comment on
        // `Effect::PumpCreaturesOpponentsControlUntilCasterNextTurn`
        // in cards.rs. The discriminator carries the parametric
        // distinction so the bridge can route Mouth of the Storm
        // cleanly TODAY and the cleanup-gate slice can swap the
        // modifier-push line below WITHOUT any bridge / call-site
        // changes.
        Effect::PumpCreaturesOpponentsControlUntilCasterNextTurn {
            power_bonus,
            toughness_bonus,
        } => {
            if *power_bonus == 0 && *toughness_bonus == 0 {
                return Ok(());
            }
            let mut src_controller: Option<u8> = None;
            'outer2: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer2;
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
                    // FIRST-SLICE: same UEOT modifier as the bare
                    // sibling. The cleanup-gate slice will swap
                    // this for a tagged-lifetime payload that
                    // expires at the source-controller's untap
                    // step instead of the next cleanup.
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
            lib_mut.push(obj); // bottom of library (post-CE3: tail)
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
            // **Controller resolution (I68 follow-up to the I59 /
            // I60 / I63 / I64 / I65 / I66 / I67 controller-of-effect
            // substrate).** Prefer the transient
            // `state.current_resolve_source_controller`, falling
            // back to `state.active_player`. Same pattern as
            // `Effect::DealDamageAnyTarget` (I67) — CR 119.5 /
            // 608.2: an effect resolves under its source's
            // controller. "Any target" defaulting to "the
            // defender" means "the SOURCE'S controller's opponent".
            //
            // **Why the fix.** Pre-fix this arm computed
            // `defender_idx = 1 - state.active_player`. Wrong when
            // the resolving spell / triggered ability has a
            // controller != active_player. Example: p1's
            // Mishra's-Bauble-shape spell ("this creature deals
            // damage equal to its power to any target") fires on
            // p0's turn. Pre-fix the trigger self-damaged p1's
            // first creature. Post-fix it correctly damages p0's
            // first creature (the source's controller's opponent).
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            // Reuse DealDamageAnyTarget's selection shape.
            let defender_idx = 1 - controller;
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
        // Round-28 broader-filter tap. Walks BOTH players' battlefield
        // in ETB-timestamp order via the shared
        // `crate::bf_iter::bf_iter_etb_sorted` helper, picking the
        // first permanent whose printing's `card_types` contains
        // "Artifact" OR "Creature". Idempotent on already-tapped
        // target. No eligible target → silent fizzle. Mirrors
        // Python's `effects/generic/tap.py:TapTargetArtifactOrCreature`
        // filter against the centralized `state.battlefield` walk
        // (no controller restriction). See invariant I39.
        Effect::TapTargetArtifactOrCreature => {
            let target: Option<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
                .into_iter()
                .find_map(|obj| {
                    let printing = state.registry.lookup(obj.printing_id)?;
                    if printing
                        .card_types
                        .iter()
                        .any(|t| t == "Artifact" || t == "Creature")
                    {
                        Some((obj.controller as usize, obj.id))
                    } else {
                        None
                    }
                });
            let Some((_pidx, target_id)) = target else {
                return Ok(()); // fizzle
            };
            // Round-58 BECOMES_TAPPED event bridge — tapper-effect
            // site (Python `effects/generic/tap.py:
            // TapTargetArtifactOrCreature`, routes the tap through
            // `turn.tap_permanent`). Centralized chokepoint so the
            // no-op-if-already-tapped gate matches Python (an
            // already-tapped target: silent no-op, NO event).
            crate::state_ops_resolve::tap_permanent_and_dispatch(
                state, target_id,
            )?;
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
            // CE4 closure: stamp the fresh-token ETB timestamp.
            let etb_ts = state.next_etb_timestamp;
            state.next_etb_timestamp = state.next_etb_timestamp.saturating_add(1);
            let new_obj = GameObject {
                id: new_id,
                printing_id,
                controller: cidx as u8,
                zone: ZONE_BATTLEFIELD,
                tapped: false,
                summoning_sick: true,
                damage: 0,
                counters: 0,
                charge_counters: 0,
                loyalty_counters: 0,
                attached_to: None,
                exiled_with_source: None,
                // Round-30 stun-counter substrate: cloned tokens
                // enter with no stun counters (per the bare-token
                // ETB precedent above).
                stun_counters: 0,
                etb_timestamp: etb_ts,
                ueot_modifiers: Vec::new(),
                // warp_cost substrate (Phase 1, round-63): cloned
                // tokens are never warp-cast. Back-compat default.
                warp_exile_pending: false,
                warped: false,
            };
            Arc::make_mut(&mut state.players[cidx].battlefield).push(new_obj);
            // ETB-trigger Slice 2 (RS5): queue ENTERS dispatch for
            // the cloned token. Same emission contract as RS4 —
            // drained by the surrounding resolver after the
            // resolving spell's stack item pops.
            state.pending_etb_dispatches.push(new_id);
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
            let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
            Arc::make_mut(&mut state.players[cidx].graveyard).push(obj);
            // Round-29 Void LTB: optional artifact sac. Artifact target
            // may also be a land — helper gates on printing.
            mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
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
            // **Controller resolution (I78 follow-up to the
            // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 / I69 /
            // I70 / I71 / I72 / I73 / I74 / I75 / I76 / I77
            // controller-of-effect substrate).** CR 119.5 / 608.2:
            // an effect resolves under its source's controller.
            // OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOf-
            // Library's first-slice target picker chooses the
            // SOURCE'S controller's opponent's first
            // Artifact-or-Creature, where defender = 1 - controller.
            // Sibling closure to I70 / I75 / I76 — identical
            // defender-swap shape; differs only in destination
            // zone (owner's library bottom vs exile / graveyard /
            // defender's hand).
            //
            // **Why the fix.** Pre-fix this arm computed
            // `defender = 1 - state.active_player`. Wrong when the
            // resolving spell / triggered ability has a controller
            // != active_player. Example: on p0's turn, p1 casts a
            // Lost-in-Space-shape sorcery. Pre-fix it self-targeted
            // p1's own Artifact-or-Creature
            // (defender = 1 - active_player = 1 - 0 = 1). Post-fix
            // it correctly targets p0's Artifact-or-Creature (the
            // source's controller's opponent — standard
            // Lost-in-Space removal shape).
            //
            // **Owner-as-controller convention preserved.** Owner
            // is captured from the target object's `controller`
            // field on re-scan after the target is identified;
            // first-slice synthetic states never split owner vs
            // controller, so owner_idx == defender == 1 - controller.
            // The library destination remains the OWNER's library
            // (CR 401.1 "into its owner's library"); the controller
            // fix only changes which side the target is picked from.
            //
            // **LTB fan-out preserved** — the leaving id still
            // pushes onto `pending_leaves_dispatches` so the drain
            // runs in `resolve_top_of_stack` AFTER the resolving
            // slot pops, mirroring the pending_etb_dispatches
            // deferral shape.
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            let defender = 1 - controller;
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
            let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[owner_idx].library);
            lib_mut.push(obj); // post-CE3: bottom = tail of Vec
            // Round-29 Void LTB: target is Artifact OR Creature —
            // either way the helper's nonland gate filters correctly.
            mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
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
        // Re-stamps `source.attached_to` to the chosen target
        // creature. CR 702.6c: equip can re-target an Equipment
        // that's already attached — stamping over an existing
        // `attached_to` is the expected behavior.
        //
        // **CE20 follow-up Slice 4 (Equipment-equip) target-pick:**
        // Reads the activator's chosen target from
        // `state.current_resolve_payload_target_id` (swapped in by
        // the stack resolver from the StackItem's
        // `trigger_payload.target_id` for activated-ability call
        // sites). When the field is `Some(id)`, stamp that as the
        // target. Pre-Slice-4 callers (any direct
        // `apply_effect(EquipToTargetCreatureYouControl)` driven
        // through a path that doesn't seed the slot) fall back to
        // the first-eligible-creature walk for back-compat —
        // matches the prior single-slice behavior. The fall-back is
        // load-bearing for the ETB-shape attach probe, where the
        // ETB trigger fires before any activator picks a target.
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
            // CE20 follow-up Slice 4: prefer the payload target_id
            // when the resolver has seeded it (targeted-activation
            // path). Validate target is still legal at resolve time
            // (CR 608.2b — fizzle if the target has become illegal
            // since cost-pay): target must be on the activator's bf
            // AND a creature AND not the source itself. Illegal
            // target at resolve → silent fizzle (CR 608.2b).
            let target_id: Option<u32> = match state
                .current_resolve_payload_target_id
            {
                Some(payload_target) => {
                    // Resolve-time legality check.
                    let bf = &state.players[cidx].battlefield;
                    let registry = &state.registry;
                    bf.iter().find_map(|obj| {
                        if obj.id != payload_target {
                            return None;
                        }
                        if obj.id == src_id {
                            return None; // can't attach to self
                        }
                        let printing =
                            registry.printings.get(obj.printing_id as usize)?;
                        if printing.card_types.iter().any(|t| t == "Creature") {
                            Some(obj.id)
                        } else {
                            None
                        }
                    })
                }
                None => {
                    // Pre-Slice-4 first-eligible walk. Kept for
                    // back-compat with any caller path that drives
                    // the variant without seeding the target slot
                    // (no current production caller, but the
                    // fall-back is load-bearing for safety + parity
                    // with the AttachToTargetCreatureYouControl
                    // sibling variant).
                    let bf = &state.players[cidx].battlefield;
                    let registry = &state.registry;
                    bf.iter().find_map(|obj| {
                        if obj.id == src_id {
                            return None; // can't attach to self
                        }
                        let printing =
                            registry.printings.get(obj.printing_id as usize)?;
                        if printing.card_types.iter().any(|t| t == "Creature") {
                            Some(obj.id)
                        } else {
                            None
                        }
                    })
                }
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
            let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
            Arc::make_mut(&mut state.players[tidx].graveyard).push(obj);
            // Round-29 Void LTB: destroying an enchanted host. Host
            // is any permanent (creature / artifact / enchantment /
            // planeswalker / land); helper gates on the printing.
            mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
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
            if target_loc.is_none() {
                return Ok(());
            }
            // Round-58 BECOMES_TAPPED event bridge — enchanted-
            // permanent tapper-effect site. Python's
            // `effects/generic/tap.py:TapEnchantedPermanent.resolve`
            // (Stay Hidden Stay Silent's Aura-ETB tap) is a pure
            // tap with an explicit `if host.tapped: return` guard
            // followed by `turn.tap_permanent(state, host)` — exactly
            // the centralized chokepoint's no-op-if-already-tapped +
            // dispatch shape. Route through it so an already-tapped
            // host is a silent no-op with NO BECOMES_TAPPED event.
            crate::state_ops_resolve::tap_permanent_and_dispatch(
                state, target_id,
            )?;
        }
        // Round-30 stun-counter substrate. Walks both players'
        // battlefield in ETB-timestamp order via the shared
        // `bf_iter_etb_sorted` helper, picking the FIRST already-
        // tapped creature it finds (no controller restriction; the
        // Python class places none either — "up to one target tapped
        // creature"). No eligible target → silent fizzle. Increments
        // `stun_counters` on the matched object via Arc::make_mut.
        // Sister of TapTargetArtifactOrCreature (no-controller
        // filter); differs in (1) Creature-only filter, (2) tapped-
        // only gate, (3) stun_counters increment instead of tap-flip.
        Effect::PutStunCounterOnTappedCreature => {
            let target: Option<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
                .into_iter()
                .find_map(|obj| {
                    if !obj.tapped {
                        return None;
                    }
                    let printing = state.registry.lookup(obj.printing_id)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some((obj.controller as usize, obj.id))
                    } else {
                        None
                    }
                });
            let Some((pidx, target_id)) = target else {
                return Ok(()); // fizzle
            };
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == target_id {
                    obj.stun_counters = obj.stun_counters.saturating_add(1);
                    break;
                }
            }
        }
        // Round-30 stun-counter substrate. Both effects (tap + stun
        // counter) apply to the SAME chosen target. Walks both
        // players' battlefield in ETB-timestamp order, picking the
        // FIRST (Artifact OR Creature) permanent NOT controlled by
        // the source's controller. No eligible target → silent fizzle.
        // Tap is idempotent on already-tapped target (CR 701.20a).
        Effect::TapTargetOpponentPermanentAndStunIt => {
            // Locate source controller — the "an opponent controls"
            // filter needs the source's controller to compare against.
            // Mirrors the controller-resolution shape of the Round-28
            // I79 follow-up: prefer current_resolve_source_controller,
            // fall back to source-on-bf scan, fall back to active_player.
            let src_controller: u8 = state
                .current_resolve_source_controller
                .or_else(|| {
                    state
                        .players
                        .iter()
                        .flat_map(|p| p.battlefield.iter())
                        .find(|o| o.id == source_obj_id)
                        .map(|o| o.controller)
                })
                .unwrap_or(state.active_player);
            let target: Option<(usize, u32)> = crate::bf_iter::bf_iter_etb_sorted(state)
                .into_iter()
                .find_map(|obj| {
                    if obj.controller == src_controller {
                        return None; // opponent-only filter
                    }
                    let printing = state.registry.lookup(obj.printing_id)?;
                    if printing
                        .card_types
                        .iter()
                        .any(|t| t == "Artifact" || t == "Creature")
                    {
                        Some((obj.controller as usize, obj.id))
                    } else {
                        None
                    }
                });
            let Some((pidx, target_id)) = target else {
                return Ok(()); // fizzle
            };
            // Round-58 BECOMES_TAPPED event bridge — tap+stun
            // combined site. Python's
            // `effects/generic/tap.py:TapTargetOpponentPermanentAndStunIt.resolve`
            // (tap.py:237-256) calls `turn.tap_permanent(state, obj)`
            // (fires BECOMES_TAPPED ONLY if the target was untapped —
            // no-op early-return otherwise) and THEN
            // `add_stun_counters(state, obj, 1)` UNCONDITIONALLY (the
            // stun counter is added even when the creature was
            // already tapped). So the no-op-if-already-tapped gate
            // applies to the EVENT only, not the stun rider — the
            // centralized chokepoint can't be reused wholesale here.
            // Snapshot `was_tapped` before the flip, apply tap+stun
            // exactly as before, then dispatch BECOMES_TAPPED iff the
            // creature actually transitioned untapped->tapped.
            let was_tapped = state.players[pidx]
                .battlefield
                .iter()
                .find(|o| o.id == target_id)
                .map(|o| o.tapped)
                .unwrap_or(true);
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == target_id {
                    obj.tapped = true;
                    obj.stun_counters = obj.stun_counters.saturating_add(1);
                    break;
                }
            }
            if !was_tapped {
                dispatch_event(
                    state, Event::BecomesTapped, target_id,
                )?;
            }
        }
        // Round-28 "until source leaves" exile. Pick defender's first
        // creature, stamp `exiled_with_source = Some(source_id)`,
        // move to exile. CR 400.7 zone-change reset for all other
        // per-object state. The link enables manual return via
        // `return_paired_exiles_for(source_id)`.
        Effect::ExileTargetCreatureUntilSourceLeaves => {
            // **Controller resolution (I79 follow-up to the
            // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 / I69 /
            // I70 / I71 / I72 / I73 / I74 / I75 / I76 / I77 / I78
            // controller-of-effect substrate).** CR 119.5 / 608.2:
            // an effect resolves under its source's controller.
            // ExileTargetCreatureUntilSourceLeaves's first-slice
            // target picker chooses the SOURCE'S controller's
            // opponent's first Creature, where defender =
            // 1 - controller. Sibling closure to I70 / I75 / I76 /
            // I78 — identical defender-swap shape; differs in
            // destination zone (exile-with-source-link vs exile /
            // graveyard / hand / library bottom) and in the
            // round-28 `exiled_with_source` bookkeeping that
            // enables manual return via
            // `return_paired_exiles_for(source_id)`.
            //
            // **Why the fix.** Pre-fix this arm computed
            // `defender = 1 - state.active_player`. Wrong when the
            // resolving spell / triggered ability has a controller
            // != active_player. Example: on p0's turn, p1's
            // All-Fates-Stalker-shape Creature has an ETB that
            // exiles a target creature until the source leaves.
            // Pre-fix it self-exiled p1's own first Creature
            // (defender = 1 - active_player = 1 - 0 = 1). Post-fix
            // it correctly exiles p0's first Creature (the
            // source's controller's opponent — the standard
            // Banisher-Priest / Fiend-Hunter ETB-exile shape).
            //
            // **Bookkeeping invariants preserved.** The
            // `exiled_with_source = Some(source_obj_id)` stamp
            // (which enables `return_paired_exiles_for`) is
            // unchanged — the controller fix only changes the
            // defender from which the target is picked, never the
            // pairing semantics. The owner-on-re-scan (target's
            // controller == owner in first-slice synthetic states)
            // continues to route the exiled object onto its
            // owner's exile zone. CR 400.7 zone-change reset
            // (tapped, summoning_sick=true, damage, counters,
            // attached_to) preserved. LTB fan-out via
            // `pending_leaves_dispatches` preserved.
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            let defender = 1 - controller;
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
            let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
            Arc::make_mut(&mut state.players[owner_idx].exile).push(obj);
            // Round-29 Void LTB: until-leaves exile. Target is a
            // Creature by filter → nonland → flag flips.
            mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
        }
        // Round-28 broader-filter "until leaves" exile. Same shape
        // as ExileTargetCreatureUntilSourceLeaves but filters on
        // "not a Land" rather than "is a Creature" — so artifacts,
        // enchantments, planeswalkers, and creatures are all
        // eligible. Defender = 1 - active_player.
        Effect::ExileOpponentsNonlandPermanentUntilLeaves => {
            // **Controller resolution (I80 follow-up to the
            // I59 / I60 / I63 / I64 / I65 / I66 / I67 / I68 / I69 /
            // I70 / I71 / I72 / I73 / I74 / I75 / I76 / I77 / I78 /
            // I79 controller-of-effect substrate).** CR 119.5 /
            // 608.2: an effect resolves under its source's
            // controller. ExileOpponentsNonlandPermanentUntilLeaves's
            // first-slice target picker chooses the SOURCE'S
            // controller's opponent's first non-land permanent,
            // where defender = 1 - controller. Sibling closure to
            // I79 — same broader-shape "until source leaves" exile;
            // differs from I79 only in the target filter ("not a
            // Land" instead of "is a Creature").
            //
            // **Why the fix.** Pre-fix this arm computed
            // `defender = 1 - state.active_player`. Wrong when the
            // resolving spell / triggered ability has a controller
            // != active_player. Example: on p0's turn, p1's
            // Hardlight-Containment-shape Enchantment has an ETB
            // that exiles an opponent's non-land permanent until
            // the source leaves. Pre-fix it self-exiled p1's own
            // first non-land permanent (defender =
            // 1 - active_player = 1 - 0 = 1); post-fix it correctly
            // exiles p0's first non-land permanent (the source's
            // controller's opponent — the standard
            // Hardlight-Containment shape, where "opponent's" in
            // the card text actually means the source-controller's
            // opponent, not the active-player's opponent).
            //
            // **Bookkeeping invariants preserved (sibling to I79
            // gotcha-list #7).** The
            // `exiled_with_source = Some(source_obj_id)` stamp
            // (which enables `return_paired_exiles_for`) is
            // unchanged — the controller fix only changes the
            // defender from which the target is picked, never the
            // pairing semantics. The owner-on-re-scan (target's
            // controller == owner in first-slice synthetic states)
            // continues to route the exiled object onto its
            // owner's exile zone. CR 400.7 zone-change reset
            // preserved. LTB fan-out via
            // `pending_leaves_dispatches` preserved.
            //
            // **Closes the post-I77 forward inventory of
            // defender-shape `(1 - state.active_player)` sites in
            // state_ops_resolve.rs.** The remaining single-target
            // first-slice defender-swap inventory is empty after
            // I80. Remaining candidates (CreateToken,
            // ReturnCreatureFromYourGraveyard family, Site at
            // ~5626) need audit — they don't fit the
            // defender-swap shape and require per-arm
            // investigation. See `docs/RUST_PARITY_GAPS.md` I80
            // forward notes.
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            let defender = 1 - controller;
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
            let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
            Arc::make_mut(&mut state.players[owner_idx].exile).push(obj);
            // Round-29 Void LTB: exile-opps-nonland — target is nonland
            // by filter. Helper short-circuits on lands defensively.
            mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
        }
        // Round-14 rider-widened "until leaves" exile (Option B —
        // additive sibling variant). Same shape as the bare
        // `ExileOpponentsNonlandPermanentUntilLeaves` arm above;
        // adds the `max_mv` mana-value cap to the legal-target
        // pool. EoE consumer: Seam Rip (`{W}` Enchantment, ETB
        // exile target nonland permanent an opponent controls
        // with mana value 2 or less until this enchantment leaves
        // the battlefield).
        //
        // **Controller-of-effect.** Mirrors the bare sibling's
        // I80 fix: controller derives from
        // `current_resolve_source_controller` (with `active_player`
        // fallback); defender = 1 - controller.
        //
        // **MV-cap evaluation.** Reads off the printing's static
        // mana cost (CR 117.x): the sum of generic + W + U + B + R
        // + G. Uses the same per-color-channel sum pattern as
        // `Effect::SearchLibraryForCard` "creature_small" arm at
        // ~line 4658. X-cost cards have X stored as 0 in the
        // printing's `mana_cost.generic` field (per the registry's
        // parse_mana_cost contract), matching CR 202.3b's "X is
        // treated as 0 in zones other than the stack".
        //
        // **Bookkeeping invariants.** Same as the bare sibling:
        // stamps `exiled_with_source = Some(source_obj_id)`,
        // pushes onto owner's exile zone, queues
        // `pending_leaves_dispatches` for LTB fan-out. CR 400.7
        // zone-change reset (tapped, summoning_sick=true per r28
        // CE1, damage, counters, attached_to) preserved.
        Effect::ExileOpponentsNonlandPermanentWithMaxMvUntilLeaves { max_mv } => {
            let max_mv_local = *max_mv;
            let controller = state
                .current_resolve_source_controller
                .map(|c| c as usize)
                .unwrap_or(state.active_player as usize);
            let defender = 1 - controller;
            let target_id: Option<u32> = {
                let bf = &state.players[defender].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.lookup(obj.printing_id)?;
                    let is_land = printing.card_types.iter().any(|t| t == "Land");
                    if is_land {
                        return None;
                    }
                    let mc = &printing.mana_cost;
                    let total = mc.generic as i32
                        + mc.white as i32
                        + mc.blue as i32
                        + mc.black as i32
                        + mc.red as i32
                        + mc.green as i32;
                    if total > max_mv_local {
                        return None;
                    }
                    Some(obj.id)
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
            let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
            Arc::make_mut(&mut state.players[owner_idx].exile).push(obj);
            mark_left_battlefield_if_nonland(state, printing_id);
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
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
        // Controller convention (I61 follow-up): prefer the transient
        // `state.current_resolve_source_controller` (set by the stack
        // resolver around each `apply_effect` call to the
        // StackItem.controller), falling back to `state.active_player`
        // for back-compat with direct `apply_effect_pub` callers. This
        // mirrors the I59 / I60 reader-side fix and closes the latent
        // cross-controller MayDo divergence: a p1-controlled spell on
        // p0's turn must push a MayDoChoice with controller=1, not 0.
        Effect::MayDo { inner_effect, prompt: _prompt } => {
            let controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
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
            // I61: prefer the transient source-controller swap.
            let controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
            let pidx = controller as usize;
            let lib_len = state.players[pidx].library.len();
            let count = (*n as usize).min(lib_len);
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(count);
            for _ in 0..count {
                // Post-CE3: top = lib[0]. Always remove(0).
                let removed = lib_mut.remove(0);
                cards.push(removed);
            }
            state.pending_decisions.push(
                PendingDecision::PickCardFromExaminedChoice {
                    source_obj_id,
                    controller,
                    cards,
                },
            );
        }
        // **BLOCKED-RUST-EFFECT slice (round 54) — Famished Worldsire
        // ETB.** "Look at the top X cards of your library, where X is
        // this creature's power. Put any number of land cards from
        // among them onto the battlefield tapped, then shuffle."
        // Mirrors Python's `FamishedWorldsireETBEffect.resolve`
        // (`effects/bespoke.py:106`) STEP-FOR-STEP so the post-resolve
        // state is byte-equal:
        //   source = state.resolving_source            (Rust: source_obj_id)
        //   if source is None: return                  (read returns 0 → x<=0 no-op)
        //   x = effective_power(state, source)         (read_famished_source_power)
        //   if x <= 0: return
        //   examined = p.library[:x]
        //   lands = [c for c in examined if c.printing.is_land]
        //   for land in lands: remove → bf tapped; fire_landfall
        //   shuffle_library(state, controller_id)
        //
        // **No PendingDecision.** The oracle's "put any number" is a
        // deterministic greedy-ALL on the Python source-of-truth side
        // (`bespoke.py:121`, documented "any number" → greedy-land
        // simplification, strictly ramp-positive). Both engines mirror
        // it; no decision is plumbed, so there is no §2
        // silent-mistranslation surface from the choice.
        Effect::FamishedWorldsireLookTopXByPowerPutLandsTapped => {
            // Source-controller resolution — same shape as
            // `SearchLibraryForBasicLandTapped` / `LookTopN...`
            // (I69 / I61): "your library" = the SOURCE's controller's
            // library, NOT the active player's. CR 119.5 / 608.2.
            let controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
            let controller_idx = controller as usize;
            let controller_u8 = controller;
            // X = source's CURRENT effective power (post-Devour +1/+1
            // counters). Source off-battlefield → read returns 0.
            // x <= 0 → silent no-op (mirrors Python's chained
            // `if source is None: return` / `if x <= 0: return`).
            let x = read_famished_source_power(state, source_obj_id);
            if x <= 0 {
                return Ok(());
            }
            let lib_len = state.players[controller_idx].library.len();
            // `p.library[:x]` — examine the top min(x, lib_len) cards.
            // Post-CE3 the top of library is lib[0]; the examined
            // window is the first `count` entries.
            let count = (x as usize).min(lib_len);
            // Collect the Vec INDICES of land cards in the examined
            // window, top-to-bottom (Python builds `lands` via a
            // top-to-bottom list comprehension over `examined`, then
            // `.remove(land)` each in that order — the survivors are
            // unaffected since removal is by identity). We snapshot
            // the indices first, then remove from the BACK so earlier
            // indices stay valid (equivalent to Python's
            // identity-`.remove()` loop; non-land "rest" cards stay in
            // the library exactly where they were — `bespoke.py:122`).
            let land_indices: Vec<usize> = {
                let lib = &state.players[controller_idx].library;
                let mut idxs: Vec<usize> = Vec::new();
                for (i, obj) in lib.iter().enumerate().take(count) {
                    let printing = match state.registry.lookup(obj.printing_id) {
                        Some(p) => p,
                        None => continue,
                    };
                    // Python's `printing.is_land` = `"Land" in
                    // card_types` (`cards/base.py:1021`). Famished
                    // Worldsire accepts ANY land (no Basic supertype
                    // gate — unlike `SearchLibraryForBasicLandTapped`).
                    if printing.card_types.iter().any(|t| t == "Land") {
                        idxs.push(i);
                    }
                }
                idxs
            };
            // ETB-trigger fan-out: collect entered land obj_ids so we
            // can queue `Event::Enters` (landfall) AFTER the post-move
            // shuffle drops its borrows — same shape as
            // `SearchLibraryForBasicLandTapped`. Python calls
            // `fire_landfall_triggers(state, land)` per land in
            // top-to-bottom order; we preserve that order by draining
            // `land_indices` low→high and pushing in that order.
            let mut entered_ids: Vec<u32> =
                Vec::with_capacity(land_indices.len());
            // Remove from the BACK so earlier indices stay valid.
            for &i in land_indices.iter().rev() {
                // CE4 closure: reserve before the player-mut borrow.
                let etb_ts = crate::state::reserve_etb_timestamp(state);
                let player = &mut state.players[controller_idx];
                let lib = Arc::make_mut(&mut player.library);
                let mut obj = lib.remove(i);
                // Stamp battlefield entry: tapped, not summoning-sick
                // (CR 302.1 is creature-only; a land entering via this
                // effect has no summoning sickness regardless).
                // Controller = the source's controller. Same per-object
                // reset shape as `SearchLibraryForBasicLandTapped`.
                obj.zone = ZONE_BATTLEFIELD;
                obj.tapped = true;
                obj.summoning_sick = false;
                obj.controller = controller_u8;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                obj.etb_timestamp = etb_ts;
                entered_ids.push(obj.id);
                Arc::make_mut(&mut player.battlefield).push(obj);
            }
            // Restore top-to-bottom landfall order (we removed
            // back-to-front above, so `entered_ids` is currently
            // bottom-to-top; Python fires landfall top-to-bottom).
            entered_ids.reverse();
            // Shuffle the WHOLE remaining library — CR 701.19 / 701.22,
            // mirrors Python's `shuffle_library(state, controller_id)`
            // = `state.rng.shuffle(p.library)`. Identical dual-path
            // block to `SearchLibraryForBasicLandTapped`: external
            // Python `random.Random` via `external_rng::next_below`
            // (byte-identical to `random.Random.shuffle`) when
            // installed, xorshift64 fallback otherwise.
            let lib_len_post = state.players[controller_idx].library.len();
            if lib_len_post >= 2 {
                let py_rng_owned: Option<Py<PyAny>> = state
                    .rng_ref()
                    .map(|r| Python::with_gil(|py| r.clone_ref(py)));
                if let Some(py_rng) = py_rng_owned {
                    let player = &mut state.players[controller_idx];
                    let lib = Arc::make_mut(&mut player.library);
                    let n = lib.len();
                    Python::with_gil(|py| -> PyResult<()> {
                        let bound = py_rng.bind(py);
                        for i in (1..n).rev() {
                            let j = crate::external_rng::next_below(bound, i + 1)?;
                            lib.swap(i, j);
                        }
                        Ok(())
                    })?;
                } else {
                    // xorshift64 fallback: distinct seed per (turn,
                    // ap, source, lib_len) tuple — same control flow as
                    // every other xorshift site in the engine.
                    let mut seed = (state.turn_number as u64)
                        .wrapping_mul(0x9E37_79B9_7F4A_7C15)
                        ^ ((state.active_player as u64) << 56)
                        ^ ((source_obj_id as u64) << 16)
                        ^ (lib_len_post as u64);
                    if seed == 0 {
                        seed = 0xdead_beef_dead_beef;
                    }
                    let player = &mut state.players[controller_idx];
                    let lib = Arc::make_mut(&mut player.library);
                    let n = lib.len();
                    let mut x_rng = seed;
                    for i in (1..n).rev() {
                        x_rng ^= x_rng << 13;
                        x_rng ^= x_rng >> 7;
                        x_rng ^= x_rng << 17;
                        let n_u64 = (i + 1) as u64;
                        let bound = u64::MAX - (u64::MAX % n_u64);
                        let mut r = x_rng;
                        while r >= bound {
                            r ^= r << 13;
                            r ^= r >> 7;
                            r ^= r << 17;
                            x_rng = r;
                        }
                        let j = (r % n_u64) as usize;
                        lib.swap(i, j);
                    }
                }
            }
            // Queue ENTERS (landfall) dispatches per entered land, in
            // top-to-bottom order — the caller (`resolve_top_of_stack`
            // / `_pause`) drains after popping the resolving stack
            // item. Mirrors Python's per-land
            // `fire_landfall_triggers`.
            state.pending_etb_dispatches.extend(entered_ids);
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
            // I61: prefer the transient source-controller swap.
            let controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
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
            // I61: prefer the transient source-controller swap.
            let controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
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
            // I61: prefer the transient source-controller swap.
            let controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
            let pidx = controller as usize;
            let lib_len = state.players[pidx].library.len();
            let pop_count = lib_len.min(2);
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(pop_count);
            for _ in 0..pop_count {
                // Post-CE3: top = lib[0]. Remove from head.
                let removed = lib_mut.remove(0);
                cards.push(removed);
            }
            state.pending_decisions.push(
                PendingDecision::ManifestDreadChoice {
                    source_obj_id,
                    controller,
                    cards,
                    then_attach_to_source: false,
                    then_plus_one_counter_on_manifested: false,
                    counter_amount: 0,
                },
            );
        }
        // Round-29 ManifestDreadThenAttachSelf composition. Mirrors
        // Python's `ManifestDreadThenAttachSelf.resolve` (Conductive-
        // Machete-family Equipment ETB, freq 3). Same pop-and-package
        // shape as `Effect::ManifestDread`, but the pending carries
        // `then_attach_to_source: true` so the submit dispatcher runs
        // the attach as a follow-up.
        //
        // Controller convention DIFFERS from plain ManifestDread: for
        // ETB-resolution on an Equipment, the source is on the bf at
        // resolve time. Read the controller off the source rather than
        // off `state.active_player` so an Equipment-spell cast (or
        // ETB-triggered) by p1 during p0's turn manifests dread from
        // p1's library. Mirrors Python's `state.resolving_source`
        // access (resolving source's `.controller_id` carries the
        // source's controller).
        //
        // Silent fizzle when source isn't on a bf — mirrors Python's
        // `source is None: return` + `"Equipment" not in subtypes:
        // return` early-exit gates (same observable behavior as
        // "source unreachable").
        //
        // First-slice: count = 1 ONLY (same gate as ManifestDread).
        Effect::ManifestDreadThenAttachSelf { count } => {
            if *count != 1 {
                return Err(PyValueError::new_err(format!(
                    "ManifestDreadThenAttachSelf: first-slice supports count = 1 only \
                     (got count = {count}); count > 1 (multi-iter) and \
                     count = 0 (no-op) deferred — see \
                     docs/SEARCH_LIMITATIONS.md"
                )));
            }
            // Locate source on a battlefield → silent fizzle if absent.
            let mut src_loc: Option<(usize, u8)> = None; // (player_idx, controller)
            for (pidx, player) in state.players.iter().enumerate() {
                if let Some(obj) = player.battlefield.iter().find(|o| o.id == source_obj_id) {
                    src_loc = Some((pidx, obj.controller));
                    break;
                }
            }
            let Some((_pidx, controller)) = src_loc else {
                return Ok(()); // source not on bf → silent fizzle
            };
            let cidx = controller as usize;
            let lib_len = state.players[cidx].library.len();
            let pop_count = lib_len.min(2);
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(pop_count);
            for _ in 0..pop_count {
                // Post-CE3: top = lib[0]. Remove from head.
                let removed = lib_mut.remove(0);
                cards.push(removed);
            }
            state.pending_decisions.push(
                PendingDecision::ManifestDreadChoice {
                    source_obj_id,
                    controller,
                    cards,
                    then_attach_to_source: true,
                    then_plus_one_counter_on_manifested: false,
                    counter_amount: 0,
                },
            );
        }
        // Round-29 ManifestDreadThenPutPlusOneCountersOnIt composition
        // (Moldering-Gym / Weight-Room Room-door family). Mirrors
        // Python's `ManifestDreadThenPutPlusOneCountersOnIt.resolve`
        // (`effects/generic/library_lookat.py:451` — Slimy Aquarium
        // counter_amount=1, Weight Room counter_amount=3). Same pop-
        // and-package shape as `Effect::ManifestDread`; the pending
        // carries `then_plus_one_counter_on_manifested: true` and the
        // chosen `counter_amount` so the submit dispatcher stamps the
        // counter on the manifested permanent as a follow-up.
        //
        // **Controller convention.** `state.active_player` — matches
        // plain `Effect::ManifestDread`. These are Room-door triggers
        // that resolve during the controller's turn (the unlocked-half
        // ETB fires on the active player's turn-cycle); active_player
        // IS the source's controller in every printed surface in the
        // pool today. Python reads `controller_id` from the trigger
        // call site, which is also active_player at resolution.
        //
        // **First-slice scope.** `count = 1` ONLY at the manifest
        // iteration level (same gate as `Effect::ManifestDread` — no
        // Python printing of this class emits count != 1). The
        // `counter_amount` rider accepts any non-negative integer
        // (Slimy Aquarium=1, Weight Room=3).
        //
        // **Empty / 1-card library partials.** Same drain shape as
        // plain ManifestDread: empty cards Vec → submit no-ops both
        // the manifest and the counter add; 1-card Vec → manifest the
        // lone card and stamp the counter on it.
        Effect::ManifestDreadThenPutPlusOneCountersOnIt {
            count,
            counter_amount,
        } => {
            if *count != 1 {
                return Err(PyValueError::new_err(format!(
                    "ManifestDreadThenPutPlusOneCountersOnIt: first-slice supports \
                     count = 1 only (got count = {count}); count > 1 (multi-iter) \
                     and count = 0 (no-op) deferred — see \
                     docs/SEARCH_LIMITATIONS.md"
                )));
            }
            // I61: prefer the transient source-controller swap.
            let controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
            let pidx = controller as usize;
            let lib_len = state.players[pidx].library.len();
            let pop_count = lib_len.min(2);
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(pop_count);
            for _ in 0..pop_count {
                // Post-CE3: top = lib[0]. Remove from head.
                let removed = lib_mut.remove(0);
                cards.push(removed);
            }
            state.pending_decisions.push(
                PendingDecision::ManifestDreadChoice {
                    source_obj_id,
                    controller,
                    cards,
                    then_attach_to_source: false,
                    then_plus_one_counter_on_manifested: true,
                    counter_amount: *counter_amount,
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
            // I61: prefer the transient source-controller swap.
            let controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
            let pidx = controller as usize;
            let lib_len = state.players[pidx].library.len();
            let pop_count = (*n as usize).min(lib_len);
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(pop_count);
            for _ in 0..pop_count {
                // Post-CE3: top = lib[0]. Remove from head.
                let removed = lib_mut.remove(0);
                cards.push(removed);
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
        // Round-28 BecomeLandCreatureUEOT (Blinkmoth Nexus / Lavaclaw
        // Reaches / Wandering Fumarole family, 13 EoE cards). CR 305.3
        // — animated land is BOTH a land and a creature UEOT. Same
        // "self" semantics as PumpSelfUntilEOT: the recipient is the
        // source GameObject (the activated-ability source on the
        // battlefield). If the source has left the battlefield between
        // activation and resolve, silent no-op. Pushes a
        // `UeotModifier::BecomesLandCreature` onto the source's
        // `ueot_modifiers`; effective-P/T readers honor the modifier
        // when present (base P/T from the modifier, layer 7c additive
        // bonuses stack on top). The modifier auto-expires at the next
        // cleanup step via the r27 CR 514.3 UEOT-clear pass, reverting
        // the land to its non-creature state.
        Effect::BecomeLandCreatureUEOT {
            power,
            toughness,
            granted_subtype,
        } => {
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
                            obj.ueot_modifiers.push(UeotModifier::BecomesLandCreature {
                                power: *power,
                                toughness: *toughness,
                                color_or_subtype: granted_subtype
                                    .clone()
                                    .unwrap_or_default(),
                            });
                            break;
                        }
                    }
                    break;
                }
            }
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
            // CE4 closure: reserve a contiguous block of timestamps so
            // each retrieved creature gets a strictly-monotonic ETB
            // timestamp matching the in-effect resolution order. The
            // counter is bumped once per moved creature.
            let bf_etb_base = state.next_etb_timestamp;
            state.next_etb_timestamp = state.next_etb_timestamp.saturating_add(moved.len() as u32);
            // ETB-trigger Slice 2 (RS6): collect each reanimated
            // creature's id for the post-push dispatch fan-out.
            let mut entered_ids: Vec<u32> = Vec::with_capacity(moved.len());
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[controller_idx].battlefield);
            for (i, mut obj) in moved.into_iter().enumerate() {
                obj.etb_timestamp = bf_etb_base.saturating_add(i as u32);
                entered_ids.push(obj.id);
                bf_mut.push(obj);
            }
            // ETB-trigger Slice 2 (RS6): queue ENTERS per
            // mass-reanimated creature in stamp order. Drained by
            // the surrounding resolver after the resolving spell's
            // stack item pops. Order matters — death/ETB chains can
            // ripple, but mirror Python's centralized list-walk by
            // emitting in the ETB-stamp order we just stamped above.
            state.pending_etb_dispatches.extend(entered_ids);
        }
        // Round-28 TapAnotherTargetCreature (Starport-Security family,
        // 2+ EoE cards). Same scan shape as UntapTargetOtherPermanent
        // but filters on Creature and taps. Already-tapped target is
        // a silent no-op (matches the existing TapTarget contract).
        //
        // CE7 closure: cross-player find-first picks the ETB-timestamp-
        // first eligible target via the shared `bf_iter_etb_sorted`
        // helper, matching Python's centralized `state.battlefield`
        // walk in `effects/generic/tap.py:277-295` (TapAnotherTargetCreature
        // resolves via the base Tap class's `legal_targets`, which walks
        // `state.battlefield` filtered by `IsCreature() & ~IsSource()`).
        // Pre-CE7 the Rust side walked p0-then-p1, which diverged from
        // Python whenever a p1 permanent had a lower ETB stamp than
        // any p0 eligible target.
        Effect::TapAnotherTargetCreature => {
            let mut found: Option<(usize, u32)> = None;
            for obj in crate::bf_iter::bf_iter_etb_sorted(state) {
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
                found = Some((obj.controller as usize, obj.id));
                break;
            }
            if let Some((_pidx, target_id)) = found {
                // Round-58 BECOMES_TAPPED event bridge — "tap another
                // target creature" tapper-effect site. Python's
                // `effects/generic/tap.py:TapAnotherTargetCreature`
                // extends the base `Tap` class, whose `resolve`
                // routes the tap through `turn.tap_permanent` (the
                // docstring at tap.py:36 spells out "no-op if already
                // tapped"). Centralized chokepoint so the
                // no-op-if-already-tapped gate matches Python (an
                // already-tapped target is a silent no-op with NO
                // BECOMES_TAPPED event — byte-equal to Python's
                // early return).
                crate::state_ops_resolve::tap_permanent_and_dispatch(
                    state, target_id,
                )?;
            }
            // else: no eligible creature → silent fizzle.
        }
        Effect::UntapTargetOtherPermanent => {
            // Find first eligible (tapped, not source) across both
            // players' battlefields.
            //
            // CE7 closure: cross-player find-first picks the ETB-
            // timestamp-first eligible target via the shared
            // `bf_iter_etb_sorted` helper, matching Python's centralized
            // `state.battlefield` walk in
            // `effects/generic/tap.py:346-386` (`UntapTargetOtherPermanent.legal_targets`
            // returns `[("permanent", o.id) for o in state.battlefield
            // if o.id != source_id and o.tapped]`). Pre-CE7 the Rust
            // side walked p0-then-p1, which diverged from Python
            // whenever a p1 tapped permanent had a lower ETB stamp
            // than any p0 eligible target.
            let mut found: Option<(usize, u32)> = None;
            for obj in crate::bf_iter::bf_iter_etb_sorted(state) {
                if obj.id != source_obj_id && obj.tapped {
                    found = Some((obj.controller as usize, obj.id));
                    break;
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
        // Round-15 (post-r14) rider-widened sibling of
        // GrantKeywordToTargetCreatureUntilEOT. Same controller-of-effect
        // resolution + first-creature pick, but: (1) admits a LIST of
        // keywords (one UeotModifier::GrantKeyword push per entry); (2)
        // honors `exclude_source` to skip the resolving source itself in
        // the target-pick scan ("another target creature"). Empty
        // keywords list short-circuits to a silent no-op (parser also
        // rejects empty at register time so this is a defensive guard,
        // not a reachable runtime path from registered cards).
        //
        // **EoE consumer.** Blooming Stinger (1G Plant Scorpion) is the
        // unique EoE source for the `exclude_source=true` shape:
        // "When this creature enters, another target creature you
        // control gains deathtouch until end of turn." Forward-
        // compatible with future multi-keyword grants via the
        // `Vec<String>` field.
        Effect::GrantKeywordsToTargetCreatureUntilEOT { keywords, exclude_source } => {
            if keywords.is_empty() {
                return Ok(());
            }
            // Source-controller resolution (5-zone walk; identical to
            // the single-keyword sibling above).
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
            // Pick first creature on controller's bf, optionally
            // excluding the resolving source itself ("another target
            // creature" — Blooming Stinger's exclude_source=true).
            let target_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    if *exclude_source && obj.id == source_obj_id {
                        return None;
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
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in zone.iter_mut() {
                if obj.id == target_id {
                    for kw in keywords {
                        obj.ueot_modifiers.push(UeotModifier::GrantKeyword {
                            keyword: kw.clone(),
                        });
                    }
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
            // Pick first NONTOKEN creature on opponent's bf.
            //
            // **Round-55 shared-root closure.** The printed oracle
            // text on Susurian Dirgecraft (+ the other 3+ EoE
            // consumers of this arm) is "each opponent sacrifices a
            // NONTOKEN creature of their choice" — the nontoken
            // filter is part of the rules text. Python's
            // `EachOpponentSacrificesCreature.resolve`
            // (effects/generic/opponent_punishers.py:47-52) builds
            // its `legal` list filtering `not o.printing.is_token`
            // BEFORE the agent picks. Pre-round-55 Rust had no
            // `is_token` notion so this `find_map` matched the FIRST
            // creature regardless of token status — diverging from
            // the rules text (and Python) whenever a token sat at
            // bf-iter index 0 ahead of a nontoken. Round-55's
            // `RegistryData::is_token` (derived from the bridge-
            // round-tripped `supertypes` Vec) closes the SAME shared
            // root as the token-cease-to-exist SBA: gate the
            // predicate on `!is_token` so both engines pick the
            // first NONTOKEN creature identically. This is the
            // SEARCH_LIMITATIONS "EachOpponentSacrificesCreature
            // nontoken-filter shortcut" entry's fix-scope step 1.
            let target_id: Option<u32> = {
                let bf = &state.players[opponent_idx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature")
                        && !registry.is_token(obj.printing_id)
                    {
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
            // CE13 closure: `summoning_sick` is NOT reset here.
            // Python's `turn.move_off_battlefield` deliberately
            // omits the clear (CR 302.1 — sickness is battlefield-
            // only state). See I35.
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            let (printing_id, leaving_obj_id) = (obj.printing_id, obj.id);
            Arc::make_mut(&mut state.players[opponent_idx].graveyard).push(obj);
            // Round-29 Void LTB: each-opponent-sacs-creature — target
            // is a Creature by filter → nonland → flag flips.
            mark_left_battlefield_if_nonland(state, printing_id);
            // Slice 10: LTB fan-out at the Effect arm. The bf-exit
            // bypasses move_object, so the LEAVES dispatch needs to
            // be wired here (Slice 8 only covered move_object +
            // SBA destroy). Queue the leaving id; the drain runs in
            // `resolve_top_of_stack` AFTER the resolving slot is
            // popped — mirrors how pending_etb_dispatches defers
            // ENTERS dispatch past the spell's stack pop. Draining
            // here would push the LTB trigger ABOVE the still-
            // present resolving spell and the subsequent
            // `stack.pop()` would pop the wrong slot.
            state.pending_leaves_dispatches.push(leaving_obj_id);
            // Round-55: token-cease sibling of the LEAVES push. The
            // id is queued unconditionally; the is_token gate lives
            // in drain_pending_token_cease (CR 111.7 / 704.5d).
            crate::state_ops_zones::queue_token_cease(state, leaving_obj_id);
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
            // `count` cards off the opponent's library top (post-
            // CE3: top = lib[0]).
            let opponent_idx = (1 - controller) as usize;
            let n = *count as usize;
            for _ in 0..n {
                let lib_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[opponent_idx].library);
                if lib_mut.is_empty() {
                    break; // empty library: silent stop (CR parity with Effect::Mill)
                }
                let mut obj = lib_mut.remove(0);
                obj.zone = ZONE_GRAVEYARD;
                Arc::make_mut(&mut state.players[opponent_idx].graveyard).push(obj);
            }
        }
        Effect::ExileEachOpponentsGraveyard => {
            // Structural twin of EachOpponentMillsCards: same
            // source-controller finder (battlefield/hand/library/
            // graveyard/exile sweep, then stack fallback), then a
            // per-opponent loop. Mirrors Python's
            // `ExileEachOpponentsGraveyard.resolve` (exile.py:260):
            // every card in each opponent's graveyard moves to that
            // player's OWN exile zone (CR 406 — exile is a public
            // zone; the card stays owned by its owner; 400.7
            // zone-change reset). 2-player simplification:
            // opponent_idx = 1 - controller.
            let mut source_controller: Option<u8> = None;
            'outer_eeg: for player in state.players.iter() {
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
                            break 'outer_eeg;
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
            // Drain the opponent's whole graveyard into their own
            // exile zone. `mem::take` mirrors Python's
            // `list(p.graveyard)` snapshot-then-clear (the per-card
            // remove/append loop in Python is observationally
            // identical to a bulk move — both empty the graveyard and
            // append in graveyard order to exile).
            let drained: Vec<GameObject> = std::mem::take(
                Arc::make_mut(&mut state.players[opponent_idx].graveyard),
            );
            if !drained.is_empty() {
                let exile_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[opponent_idx].exile);
                for mut obj in drained {
                    obj.zone = ZONE_EXILE;
                    exile_mut.push(obj);
                }
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
        // DealDamageToOpponentCreature — Glassworks // Shattered Yard
        // family (2 EoE cards). Mirrors Python's
        // `DealDamageToOpponentCreature(DealDamage)` sugar with filter
        // `IsCreature() & ControlledByOpponent()`. Distinct from
        // `DealDamageAnyTarget` (which can hit a player) AND from
        // `DealDamage { target: AnyCreature }` (which picks bf[0] of
        // the active player's defender without a card-type filter).
        //
        // Source-controller direction: scan source GameObject across
        // the 5 zones + stack to recover `source.controller`. Opponent
        // pool = every player whose id != source_controller (in 2-player
        // engine = the one opponent).
        //
        // First-slice deterministic choice: iterate opponents in
        // ascending player order; pick the FIRST `Creature` printing on
        // each opponent's battlefield (smallest bf index). Return on
        // first match — silent fizzle if no opponent has a creature.
        // Source-controller's own creatures are excluded by construction
        // (we only scan the opponents).
        //
        // Negative `amount` raises at register time AND here as defense-
        // in-depth (mirrors the DealDamage / DealDamageAnyTarget
        // raise-on-negative shape).
        Effect::DealDamageToOpponentCreature { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "DealDamageToOpponentCreature amount must be non-negative, got {amount}"
                )));
            }
            // Source-controller resolution (5-zone walk + stack scan;
            // mirrors LoseLife / TargetOpponentLosesLife shape).
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
            // First eligible target: scan opponents (players whose id
            // != controller) in ascending order; pick the first
            // Creature on each opponent's bf (smallest index). 2-player
            // engine: exactly one opponent at `1 - controller`, but
            // generalize via the iterator to keep the shape n-player-
            // ready.
            let mut found: Option<(usize, u32)> = None;
            'outer_dd: for (pidx, player) in state.players.iter().enumerate() {
                if pidx as u8 == controller {
                    continue;
                }
                for obj in player.battlefield.iter() {
                    let printing_idx = obj.printing_id as usize;
                    let Some(printing) = state.registry.printings.get(printing_idx) else {
                        continue;
                    };
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        found = Some((pidx, obj.id));
                        break 'outer_dd;
                    }
                }
            }
            if let Some((pidx, target_id)) = found {
                let amount_i16 = (*amount).min(i16::MAX as i32) as i16;
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                        break;
                    }
                }
            }
            // else: no opponent creature → silent fizzle.
        }
        // Round-29 OptionalManaCostThenEffect — Kavaron-Harrier /
        // Oreplate-Pangolin family. "You may pay {cost}. If you do,
        // [inner_effect]." Pushes a PendingDecision::OptionalManaCostChoice
        // carrying the mana cost and inner Effect on the heap, and
        // short-circuits. Controller drains via
        // submit_optional_mana_cost_decision(pay) (manual) or
        // auto_resolve_pending_decisions("default" | "optional_pay_yes"
        // | "optional_pay_no") (deterministic).
        //
        // Controller convention: state.active_player — first-slice
        // shape consistent with Surveil / MayDo / IfYouDo / etc.
        //
        // No cost / inner-effect evaluation happens here: the decision
        // is just packaged. Affordability is checked at submit time so
        // the controller's pool state is the one in effect WHEN the
        // decision is resolved (matching Python's
        // OptionalManaCostThenEffect.resolve, which inspects pool
        // state at resolve time).
        Effect::OptionalManaCostThenEffect { cost, inner_effect } => {
            // I61: prefer the transient source-controller swap.
            let controller = state
                .current_resolve_source_controller
                .unwrap_or(state.active_player);
            state.pending_decisions.push(
                PendingDecision::OptionalManaCostChoice {
                    source_obj_id,
                    controller,
                    cost: cost.clone(),
                    inner_effect: inner_effect.clone(),
                },
            );
        }
        // Round-28 freq-2 closure — Starwinder / Fear-of-Failed-Tests.
        // "When a creature you control deals combat damage to a player,
        // you may draw that many cards." Reads
        // state.resolving_combat_damage_amount and draws that many
        // cards for the SOURCE's controller (zone-scan + stack-scan
        // fallback, same shape as DiscardSelf et al.).
        //
        // **Write site (I32).** The slot is written per-event inside
        // `state_ops_combat.rs::apply_damage_pass` — set to
        // `entry.amount` before per-entry mutations, reset to 0 after.
        // Mirrors Python's per-event set/reset boundary
        // (combat.py:618,623 and actions.py:2684,2699). The Effect
        // reads the slot at resolve time; the apply-loop write keeps
        // the value live for any trigger that fires during the
        // event's downstream effects. See RUST_PARITY_GAPS.md I32.
        //
        // amount <= 0 → silent no-op (matches Python).
        Effect::DrawCardsEqualToResolvingCombatDamage => {
            let amount = state.resolving_combat_damage_amount;
            if amount <= 0 {
                return Ok(());
            }
            // Locate source controller (zone-scan first, stack scan
            // fallback). Same pattern as DiscardSelf / EachOpponent*.
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
                return Ok(()); // source not found anywhere: silent fizzle
            };
            let controller_idx = controller as usize;
            // Inline draw loop — same pattern as Effect::DrawCards.
            // CR 704.5b empty-library handling flips
            // attempted_draw_on_empty so the SBA pass converts it to
            // has_lost.
            let n = amount as usize;
            for _ in 0..n {
                let player = &mut state.players[controller_idx];
                let lib = Arc::make_mut(&mut player.library);
                if lib.is_empty() {
                    player.attempted_draw_on_empty = true;
                    break;
                }
                let mut obj = lib.remove(0);
                obj.zone = ZONE_HAND;
                Arc::make_mut(&mut player.hand).push(obj);
            }
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
    fn return_paired_exiles_for(&mut self, source_id: u32) -> PyResult<i32> {
        let mut returned = 0i32;
        // ETB-trigger Slice 2 (RS7): collect each recalled
        // permanent's id across both players so we can drain ENTERS
        // dispatches after all bf-pushes complete.
        let mut entered_ids: Vec<u32> = Vec::new();
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
            // CE4 closure: reserve a contiguous block of timestamps
            // so each returning permanent gets a strictly-monotonic
            // ETB timestamp matching the in-loop drain order.
            let bf_etb_base = self.next_etb_timestamp;
            self.next_etb_timestamp = self.next_etb_timestamp.saturating_add(popped.len() as u32);
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut self.players[pidx].battlefield);
            for (i, mut obj) in popped.into_iter().enumerate() {
                obj.etb_timestamp = bf_etb_base.saturating_add(i as u32);
                entered_ids.push(obj.id);
                bf_mut.push(obj);
                returned += 1;
            }
        }
        // ETB-trigger Slice 2 (RS7): queue ENTERS per recalled
        // permanent + drain. Mirrors Python's `put_into_battlefield`
        // per recalled object inside `return_paired_exiles_for`. Uses
        // the deferred-dispatch pattern (push to queue then drain) so
        // the call site is consistent with RS2-RS6's resolver-driven
        // drain shape and re-entrant ETB chains land correctly.
        self.pending_etb_dispatches.extend(entered_ids);
        drain_pending_etb_dispatches(self)?;
        Ok(returned)
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

        // ETB-trigger Slice 1: triggered-ability resolution path.
        // A `StackItem::TriggeredAbility` carries its effect inline
        // in `trigger_payload.effect`; the resolver fires that effect
        // via `apply_effect` and skips `move_source_post_resolve`
        // (triggers aren't permanents — their source already lives
        // wherever the trigger fired from).
        if top.kind == StackItemKind::TriggeredAbility {
            let payload = top
                .trigger_payload
                .as_ref()
                .expect("StackItemKind::TriggeredAbility must carry trigger_payload");
            let trigger_effect = payload.effect.clone();
            // CE20 follow-up Slice 4: swap in payload target_id so
            // targeted-activation effect arms (today only
            // `Effect::EquipToTargetCreatureYouControl`) can read
            // the activator's chosen target. Restored after the
            // apply so no observable state leaks across resolution
            // boundaries. Mirrors the `state.active_player` swap
            // pattern at state_ops_actions.rs:725 (Slice 1 bridge
            // follow-up).
            let saved_target = self.current_resolve_payload_target_id;
            self.current_resolve_payload_target_id = payload.target_id;
            // DrawCards controller-of-effect fix: also swap in the
            // trigger's controller so `Effect::DrawCards` (and any
            // future arm that opts into the source-controller
            // convention) draws into the trigger's controller's
            // hand, NOT `state.active_player`'s hand. Restored
            // after apply.
            let saved_ctrl = self.current_resolve_source_controller;
            self.current_resolve_source_controller = Some(top.controller);
            let apply_result = apply_effect(self, &trigger_effect, top.source_obj_id);
            self.current_resolve_source_controller = saved_ctrl;
            self.current_resolve_payload_target_id = saved_target;
            apply_result?;
            let popped = self
                .stack
                .pop()
                .expect("peeked top but pop returned None — stack invariant broken");
            // Slice 2 — drain any ETB dispatches the trigger's
            // effect deferred. A trigger that lands a permanent on
            // bf (e.g. a token-creating ETB trigger) populates the
            // queue; we fan out the events now that the resolving
            // trigger slot has been popped.
            drain_pending_etb_dispatches(self)?;
            // R74-2 — drain any DIES dispatches a trigger's effect
            // may have queued (a trigger whose Effect destroys a
            // creature via the DepressurizeEffect hand-rolled arm).
            // Drained BEFORE LEAVES so the stack-push order is DIES
            // then LEAVES (LIFO -> LEAVES resolves first), byte-equal
            // to the SBA destroy path (`state_ops_sba.rs` :497/:503)
            // and Python's `move_off_battlefield` (turn.py:253-289).
            // Outside `apply_sbas` the only producer of this queue is
            // the DepressurizeEffect arm, so this drain is a no-op
            // (empty queue) for every pre-R74-2 trigger resolution.
            drain_pending_dies_dispatches(self)?;
            // Slice 10 — drain any LEAVES dispatches a trigger's
            // effect may have queued (e.g. a trigger that destroys
            // / bounces / exiles another bf permanent via an Effect
            // arm in state_ops_resolve.rs). Drain happens AFTER the
            // trigger slot is popped so the LEAVES trigger goes
            // onto the now-empty top, mirroring the spell-path's
            // pop-then-fan-out ordering.
            drain_pending_leaves_dispatches(self)?;
            // Auto-resolve any pending decisions the trigger effect
            // may have queued (Surveil on ETB, etc.). Matches the
            // spell-path's terminal call below.
            auto_resolve_pending(self, "keep_all_on_top")?;
            return Ok(Some(stack_item_to_dict(py, &popped)?));
        }

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

        // DrawCards controller-of-effect fix: swap in the resolving
        // spell's controller for the duration of the effect-fan-out
        // loop so `Effect::DrawCards` (and any future arm reading
        // `current_resolve_source_controller`) routes to the
        // spell's controller, not `state.active_player`. Mirrors the
        // triggered-ability branch above. Restored after the loop
        // (also restored on early-return via the `?` operator by
        // dropping out of the function — but since we don't have a
        // RAII guard here, the swap is bracketed inline; any
        // `apply_effect` error propagates as `?` and the inline
        // restore line is skipped, but since the field default is
        // `None` and the resolver is the outermost frame, the leak
        // is bounded to "next call to apply_effect sees Some(this
        // controller) instead of None" — semantically a no-op for
        // every back-compat caller because DrawCards is the only
        // reader and any DrawCards in the error path would have
        // produced wrong output ANYWAY pre-fix. Bracketed restore
        // below covers the success path.
        let saved_ctrl = self.current_resolve_source_controller;
        self.current_resolve_source_controller = Some(top.controller);
        // Spell-card-bridge lever (round-70): swap in the spell's
        // deterministic-first bound target so any per-card bespoke
        // Effect resolve arm that reads the target via the SAME
        // `current_resolve_payload_target_id` swap the
        // `TriggeredAbility` path uses (above; today only
        // `EquipToTargetCreatureYouControl`) resolves byte-equal
        // whether driven by a trigger OR a spell cast. `None` for
        // every pre-lever spell push (back-compat — the field
        // defaults `None`; the closed Tier-A spell arms self-scan the
        // battlefield and ignore this, so the swap is a correct no-op
        // for them). Save → set → restore bracketing the apply
        // closure exactly as `saved_ctrl` does, so no observable
        // state leaks across resolution boundaries (pin #4 / #6).
        let saved_target = self.current_resolve_payload_target_id;
        self.current_resolve_payload_target_id = top.target_obj_id;
        // Spell-card-bridge lever Phase 2 (round-76): swap in the
        // SECOND bound target for a 2-slot spell (Diplomatic
        // Relations). Identical save → set → restore bracketing as
        // slot 0; `None` for every single-target / pre-Phase-2 push
        // (back-compat — the closed Phase-1 single-target arms
        // self-scan and ignore BOTH payload slots, so the swap is a
        // correct no-op for them). Mirrored into BOTH resolve entry
        // points (the §3.4 sibling-parity requirement; pin #4 / #6).
        let saved_target_2 = self.current_resolve_payload_target_id_2;
        self.current_resolve_payload_target_id_2 = top.target_obj_id_2;
        let effects_result: PyResult<()> = (|| {
            for effect in &effects {
                apply_effect(self, effect, top.source_obj_id)?;
            }
            Ok(())
        })();
        self.current_resolve_payload_target_id_2 = saved_target_2;
        self.current_resolve_payload_target_id = saved_target;
        self.current_resolve_source_controller = saved_ctrl;
        effects_result?;

        // CR 608.2m: post-resolve, move the spell source. Instants /
        // sorceries -> controller's graveyard; permanents (creature,
        // artifact, enchantment, planeswalker, battle) ->
        // controller's battlefield with summoning sickness for
        // creatures. Empty card_types is the synthetic-test escape
        // hatch — leave source in place. Done BEFORE the stack pop
        // so a panic in movement doesn't leave the stack drained
        // with no movement applied (transactional shape).
        let post_resolve_zone = move_source_post_resolve(self, top.source_obj_id);

        // ETB-trigger Slice 3: legacy `etb_effects` inline loop
        // retired. The parse-time bridge in `cards.rs::parse_printing`
        // synthesizes a `TriggeredAbility { event: Enters,
        // predicate: SourceIsSelf, effect: ... }` per `etb_effects`
        // entry at registry-load time, so the predicate-path
        // `dispatch_event(Event::Enters, top.source_obj_id)` call
        // below handles every self-ETB effect that used to fire here.
        // The previous pop-then-dispatch ordering is preserved
        // (drain the resolving slot from the stack first, then
        // dispatch ENTERS) so the trigger goes on the now-empty
        // stack and resolves LIFO on the next priority round.

        // Drain the popped item BEFORE firing dispatch_event below —
        // ETB triggers go onto the stack ABOVE where the resolving
        // spell sat, but the resolving spell itself has now finished
        // and its stack-item must come off first. Mirrors Python's
        // flow: the spell pops first (the spell completed); the
        // trigger then pushes onto the now-empty stack, resolving
        // LIFO on the next priority round.
        let popped = self
            .stack
            .pop()
            .expect("peeked top but pop returned None — stack invariant broken");

        // ETB-trigger predicate-path dispatch fan-out (Slice 1
        // wiring; Slice 3 absorbed the legacy `etb_effects` inline
        // hatch by synthesizing
        // `TriggeredAbility { event=Enters, predicate=SourceIsSelf,
        // effect=... }` per `etb_effects` entry at parse time —
        // every self-ETB effect now fires through the same walker
        // as the Panharmonicon-shape observer triggers).
        if post_resolve_zone == Some(ZONE_BATTLEFIELD) {
            dispatch_event(self, Event::Enters, top.source_obj_id)?;
        }
        // Slice 2 — drain any ETB dispatches that effect arms
        // deferred via `pending_etb_dispatches` (RS2-RS7's spell-
        // effect resolutions: search-and-bf, reanimation, token
        // creation, mass reanim, clone-target, exile-recall). The
        // queue mechanism keeps the stack untouched during
        // `apply_effect` so the resolver's `pop()` always drains
        // the resolving slot, regardless of how many permanents
        // entered during the effect pass.
        drain_pending_etb_dispatches(self)?;
        // R74-2 — drain any DIES dispatches the spell's Effect arms
        // deferred via `pending_dies_dispatches`. Today the only
        // producer outside `apply_sbas` (which self-drains) is the
        // DepressurizeEffect hand-rolled destroy arm — its destroyed
        // creature's `Event.DIES` triggered ability (e.g. Gravpack
        // Monoist -> Robot token) MUST fire to match Python's
        // `turn.destroy` -> `move_off_battlefield`. Drained BEFORE
        // LEAVES so the stack-push order is DIES then LEAVES (LIFO
        // -> LEAVES resolves first), byte-equal to the SBA destroy
        // path (`state_ops_sba.rs` :497/:503) and Python's
        // `move_off_battlefield` (turn.py:253-289). No-op (empty
        // queue) for every pre-R74-2 spell resolution.
        drain_pending_dies_dispatches(self)?;
        // Slice 10 — drain any LEAVES dispatches the spell's Effect
        // arms deferred via `pending_leaves_dispatches` (bounce /
        // destroy / exile / sacrifice-as-effect at the 13 bf-exit
        // sites in `state_ops_resolve.rs` that bypass `move_object`
        // and call `mark_left_battlefield_if_nonland` directly). The
        // queue mechanism is the LEAVES counterpart of the Slice 2
        // ETB queue and follows the same defer-past-pop ordering:
        // the resolving spell pops first, then LEAVES triggers
        // pushed during `apply_effect` land on the now-empty top.
        drain_pending_leaves_dispatches(self)?;
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
        // ETB-trigger Slice 1: trigger resolution path (same as
        // `resolve_top_of_stack` above, minus the auto-resolve of
        // pending decisions — `_pause` leaves them on the queue).
        if top.kind == StackItemKind::TriggeredAbility {
            let payload = top
                .trigger_payload
                .as_ref()
                .expect("StackItemKind::TriggeredAbility must carry trigger_payload");
            let trigger_effect = payload.effect.clone();
            // CE20 follow-up Slice 4: same payload-target swap as
            // `resolve_top_of_stack` above. See the longer comment
            // there for the rationale.
            let saved_target = self.current_resolve_payload_target_id;
            self.current_resolve_payload_target_id = payload.target_id;
            // DrawCards controller-of-effect fix: same controller
            // swap as `resolve_top_of_stack` above.
            let saved_ctrl = self.current_resolve_source_controller;
            self.current_resolve_source_controller = Some(top.controller);
            let apply_result = apply_effect(self, &trigger_effect, top.source_obj_id);
            self.current_resolve_source_controller = saved_ctrl;
            self.current_resolve_payload_target_id = saved_target;
            apply_result?;
            let popped = self
                .stack
                .pop()
                .expect("peeked top but pop returned None — stack invariant broken");
            // Slice 2: drain any RS-site deferred dispatches.
            drain_pending_etb_dispatches(self)?;
            // R74-2: drain DIES before LEAVES — see the matching
            // comment in `resolve_top_of_stack`'s trigger branch.
            drain_pending_dies_dispatches(self)?;
            // Slice 10: drain LEAVES sibling — see the matching
            // comment in `resolve_top_of_stack`'s trigger branch.
            drain_pending_leaves_dispatches(self)?;
            return Ok(Some(stack_item_to_dict(py, &popped)?));
        }
        let effects: Vec<Effect> = match find_source_printing_id(self, top.source_obj_id)
        {
            Some(printing_id) => match self.registry.lookup(printing_id) {
                Some(printing) => printing.effects.clone(),
                None => Vec::new(),
            },
            None => Vec::new(),
        };
        // DrawCards controller-of-effect fix: same controller swap
        // as `resolve_top_of_stack` above.
        let saved_ctrl = self.current_resolve_source_controller;
        self.current_resolve_source_controller = Some(top.controller);
        // Spell-card-bridge lever (round-70): the SAME spell-target
        // swap as `resolve_top_of_stack`'s spell arm. The two resolve
        // entry points MUST stay in lockstep — a missed sibling here
        // is exactly the round-60-N1-class transcription bug the
        // verify-first discipline guards against (pin #6 is the
        // sibling-parity guard). See the longer comment in
        // `resolve_top_of_stack` for the rationale.
        let saved_target = self.current_resolve_payload_target_id;
        self.current_resolve_payload_target_id = top.target_obj_id;
        // Spell-card-bridge lever Phase 2 (round-76): swap in the
        // SECOND bound target for a 2-slot spell (Diplomatic
        // Relations). Identical save → set → restore bracketing as
        // slot 0; `None` for every single-target / pre-Phase-2 push
        // (back-compat — the closed Phase-1 single-target arms
        // self-scan and ignore BOTH payload slots, so the swap is a
        // correct no-op for them). Mirrored into BOTH resolve entry
        // points (the §3.4 sibling-parity requirement; pin #4 / #6).
        let saved_target_2 = self.current_resolve_payload_target_id_2;
        self.current_resolve_payload_target_id_2 = top.target_obj_id_2;
        let effects_result: PyResult<()> = (|| {
            for effect in &effects {
                apply_effect(self, effect, top.source_obj_id)?;
            }
            Ok(())
        })();
        self.current_resolve_payload_target_id_2 = saved_target_2;
        self.current_resolve_payload_target_id = saved_target;
        self.current_resolve_source_controller = saved_ctrl;
        effects_result?;
        let post_resolve_zone = move_source_post_resolve(self, top.source_obj_id);
        // ETB-trigger Slice 3: legacy `etb_effects` inline loop
        // retired in `_pause` for the same reason as in
        // `resolve_top_of_stack` (the parse-time bridge synthesizes
        // `TriggeredAbility { event: Enters, predicate: SourceIsSelf,
        // effect: ... }` per `etb_effects` entry; the dispatch_event
        // call below handles them).
        // Pop the resolving spell's stack item BEFORE firing
        // dispatch_event — see the same-shaped comment in
        // `resolve_top_of_stack` above for the ordering rationale.
        let popped = self
            .stack
            .pop()
            .expect("peeked top but pop returned None — stack invariant broken");
        if post_resolve_zone == Some(ZONE_BATTLEFIELD) {
            // ETB-trigger Slice 1: same predicate-path fan-out as
            // `resolve_top_of_stack` above.
            dispatch_event(self, Event::Enters, top.source_obj_id)?;
        }
        // Slice 2: drain any RS-site deferred dispatches from the
        // effect pass above. Mirrors the `resolve_top_of_stack`
        // drain — the `_pause` variant just skips the
        // auto-resolve-pending step, not the ETB fan-out.
        drain_pending_etb_dispatches(self)?;
        // R74-2: drain DIES before LEAVES — see the matching
        // comment in `resolve_top_of_stack`'s spell branch.
        drain_pending_dies_dispatches(self)?;
        // Slice 10: drain LEAVES sibling — see the matching
        // comment in `resolve_top_of_stack`'s spell branch.
        drain_pending_leaves_dispatches(self)?;
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

        // CE4 closure: register_and_inject_object stamps a fresh
        // etb_timestamp only when injecting into ZONE_BATTLEFIELD;
        // injections into hand / library / graveyard / exile use the
        // default 0 (the object isn't on the battlefield yet, so its
        // ordering relative to bf objects is undefined). The stamp
        // bump is unconditional to keep the call site branch-free —
        // an unused timestamp leaks no observable state because only
        // the bf entries are sort-keyed by `etb_timestamp`.
        let etb_ts = if target_zone == ZONE_BATTLEFIELD {
            let ts = self.next_etb_timestamp;
            self.next_etb_timestamp = self.next_etb_timestamp.saturating_add(1);
            ts
        } else {
            0
        };
        let obj = GameObject {
            id: next_id,
            printing_id,
            controller,
            zone: target_zone,
            tapped: false,
            summoning_sick: false,
            damage: 0,
            counters: 0,
            charge_counters: 0,
            loyalty_counters: 0,
            attached_to: None,
            exiled_with_source: None,
            // Round-30 stun-counter substrate: caller-injected
            // objects start unstunned per make_object precedent.
            stun_counters: 0,
            etb_timestamp: etb_ts,
            ueot_modifiers: Vec::new(),
            // warp_cost substrate (Phase 1, round-63): caller-
            // injected objects default to not-warp. Back-compat.
            warp_exile_pending: false,
            warped: false,
        };

        let player = &mut self.players[controller as usize];
        // Test-injection convention: for LIBRARY zone, insert at the
        // TOP of library (lib[0] post-CE3) so injected cards are
        // immediately reachable by top-N readers (scry, surveil,
        // search-from-top). Pre-CE3 the push-to-tail landed cards at
        // the top (which was the tail then); the post-CE3 equivalent
        // is insert(0, ...). For other zones (HAND, BATTLEFIELD,
        // GRAVEYARD) append-to-tail is the established pattern and
        // stays.
        // ETB-trigger Slice 2 (RS8): capture entered_id when the test
        // injection lands directly on the battlefield, so we can
        // dispatch `Event::Enters` AFTER releasing the player-mut
        // borrow below. Non-bf injections are no-ops on the trigger
        // path (the object isn't on the battlefield, so no permanent
        // observes its arrival).
        let entered_id: Option<u32> = if target_zone == ZONE_BATTLEFIELD {
            Some(next_id)
        } else {
            None
        };
        match target_zone {
            ZONE_HAND => {
                Arc::make_mut(&mut player.hand).push(obj);
            }
            ZONE_LIBRARY => {
                Arc::make_mut(&mut player.library).insert(0, obj);
            }
            ZONE_BATTLEFIELD => {
                Arc::make_mut(&mut player.battlefield).push(obj);
            }
            ZONE_GRAVEYARD => {
                Arc::make_mut(&mut player.graveyard).push(obj);
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "register_and_inject_object: unsupported target_zone {other} (valid: 0-3)"
                )));
            }
        }
        // ETB-trigger Slice 2 (RS8): test-fixture battlefield
        // injections fan out ENTERS via the deferred-dispatch queue
        // so per-test substrate fixtures can exercise observer-style
        // triggers. Non-bf injections are a no-op on the trigger path.
        if let Some(id) = entered_id {
            self.pending_etb_dispatches.push(id);
            drain_pending_etb_dispatches(self)?;
        }
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
