//! Decision-callback dispatcher — round-27 G20 closure.
//!
//! Round-27 introduces the **state-machine decision-callback substrate**:
//! effects that need a controller-provided choice push a
//! `PendingDecision` onto `GameState.pending_decisions` and short-
//! circuit. The caller (MCTS, parity_smoke, the test harness) inspects
//! the queue via `pending_decisions()` / `has_pending_decision()`,
//! makes a choice, and consumes the head via a variant-specific
//! `submit_*_decision` dispatcher (the only variant today:
//! `submit_surveil_decision`).
//!
//! For backwards compatibility with the round-23 deterministic-keep-
//! all-on-top behavior (and to keep `resolve_top_of_stack` callers
//! that don't want to model the decision dimension working), this
//! module also exposes `auto_resolve_pending_decisions(strategy)`:
//!
//! * `"keep_all_on_top"` — Surveil sends every observed card back to
//!   the library top in the same order it was popped (preserves the
//!   r23 baseline; bit-equal to the pre-r27 path).
//! * `"send_all_to_graveyard"` — Surveil sends every observed card
//!   to the controller's graveyard (the symmetric mill-for-graveyard-
//!   fill fast-path).
//!
//! The substrate also powers G22 (London bottom-N), G24 (Paris
//! scry-on-keep), and future `ModalChooseOne` / `ManifestDread`
//! variants. Each new variant adds a `PendingDecision` arm + a
//! `submit_*_decision` dispatcher; the queue / auto-resolve / clone /
//! fingerprint plumbing is shared.
//!
//! **Pyo3 wiring.** All public methods are `#[pymethods]` on
//! `GameState` so Python can drive the decision loop directly. The
//! dispatchers consume the head of the Vec (index 0); the auto-
//! resolve drains in FIFO order until the queue is empty.

use crate::cards::ManaCost;
use crate::state::{GameObject, GameState, PendingDecision};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::sync::Arc;

/// Whether `state.players[controller]`'s mana pool can afford `cost`
/// (same algorithm as `pay_mana_cost`'s validation phase — colored
/// requirements must be matchable by same-color mana; the remaining
/// post-colored pool must cover generic). Pure read; never mutates.
fn can_pay_mana_cost_internal(
    state: &GameState,
    controller: u8,
    cost: &ManaCost,
) -> bool {
    let idx = controller as usize;
    if idx >= 2 {
        return false;
    }
    let pool = &state.players[idx].mana_pool;
    if (pool.white as u32) < cost.white as u32
        || (pool.blue as u32) < cost.blue as u32
        || (pool.black as u32) < cost.black as u32
        || (pool.red as u32) < cost.red as u32
        || (pool.green as u32) < cost.green as u32
    {
        return false;
    }
    let rem_white = pool.white as u32 - cost.white as u32;
    let rem_blue = pool.blue as u32 - cost.blue as u32;
    let rem_black = pool.black as u32 - cost.black as u32;
    let rem_red = pool.red as u32 - cost.red as u32;
    let rem_green = pool.green as u32 - cost.green as u32;
    let rem_colorless = pool.colorless as u32;
    let rem_total = rem_white + rem_blue + rem_black + rem_red + rem_green + rem_colorless;
    rem_total >= cost.generic as u32
}

/// Atomically deduct `cost` from `state.players[controller]`'s mana
/// pool. Returns `true` on success (pool mutated, cost paid),
/// `false` on insufficient mana (pool untouched). Same drain order
/// as `pay_mana_cost`: colored first, then generic from
/// C → W → U → B → R → G.
fn pay_mana_cost_internal(
    state: &mut GameState,
    controller: u8,
    cost: &ManaCost,
) -> bool {
    if !can_pay_mana_cost_internal(state, controller, cost) {
        return false;
    }
    let idx = controller as usize;
    let pool = &mut state.players[idx].mana_pool;
    pool.white -= cost.white;
    pool.blue -= cost.blue;
    pool.black -= cost.black;
    pool.red -= cost.red;
    pool.green -= cost.green;
    let mut remaining_generic = cost.generic as u32;
    for slot in [
        &mut pool.colorless,
        &mut pool.white,
        &mut pool.blue,
        &mut pool.black,
        &mut pool.red,
        &mut pool.green,
    ] {
        if remaining_generic == 0 {
            break;
        }
        let avail = *slot as u32;
        let take = avail.min(remaining_generic);
        *slot -= take as u8;
        remaining_generic -= take;
    }
    debug_assert_eq!(remaining_generic, 0);
    true
}

/// Auto-resolve every pending decision currently on the queue using
/// `strategy`. The auto-resolver drains in FIFO order (index 0 first)
/// and consumes the entire queue. Available as a free fn so
/// `resolve_top_of_stack` can call it without crossing the
/// `#[pymethods]` boundary (E0624 friction).
///
/// Supported strategies:
/// - `"keep_all_on_top"` — every Surveil observed card returns to
///   library top in popped order (cards[0] back on top last; the
///   topmost-popped card lands on top so the library order matches
///   what it was before the surveil — the round-23 baseline).
/// - `"send_all_to_graveyard"` — every Surveil observed card moves
///   to the controller's graveyard, in popped order.
///
/// Raises `ValueError` on an unknown strategy.
pub(crate) fn auto_resolve_pending(
    state: &mut GameState,
    strategy: &str,
) -> PyResult<()> {
    // Validate strategy up-front so an unknown name doesn't drain
    // the head before failing. Transactional shape: a failed
    // strategy leaves the queue untouched.
    match strategy {
        "keep_all_on_top"
        | "send_all_to_graveyard"
        | "may_do_yes"
        | "may_do_no"
        | "pick_top"
        | "choose_mode_0"
        | "if_you_do_yes"
        | "if_you_do_no"
        | "manifest_top"
        | "reveal_yes"
        | "reveal_no"
        | "optional_pay_yes"
        | "optional_pay_no"
        | "scry_keep_top"
        | "scry_send_bottom"
        | "default" => {}
        other => {
            return Err(PyValueError::new_err(format!(
                "auto_resolve_pending_decisions: unknown strategy {other:?}; \
                 valid strategies: keep_all_on_top, send_all_to_graveyard, \
                 may_do_yes, may_do_no, pick_top, choose_mode_0, \
                 if_you_do_yes, if_you_do_no, manifest_top, reveal_yes, \
                 reveal_no, optional_pay_yes, optional_pay_no, \
                 scry_keep_top, scry_send_bottom, default"
            )))
        }
    }
    while !state.pending_decisions.is_empty() {
        let decision = state.pending_decisions.remove(0);
        match decision {
            PendingDecision::SurveilChoice {
                controller, cards, ..
            } => {
                // "default" routes Surveil to keep_all_on_top (round-23
                // baseline). MayDo-specific strategies don't apply to
                // Surveil; fall through to keep_all_on_top for
                // robustness when a multi-variant queue gets drained
                // with a MayDo-tuned strategy.
                let effective_strategy = match strategy {
                    "default" | "may_do_yes" | "may_do_no" => "keep_all_on_top",
                    s => s,
                };
                resolve_surveil_with_strategy(state, controller, cards, effective_strategy)?;
            }
            PendingDecision::MayDoChoice {
                source_obj_id,
                controller,
                inner_effect,
            } => {
                // "default" / "may_do_yes" → apply inner effect.
                // "may_do_no" → drop the decision (no inner applies).
                // Surveil-specific strategies don't apply to MayDo;
                // fall through to "yes" for robustness (matches
                // Python's no-agent-seated default).
                let say_yes = match strategy {
                    "may_do_no" => false,
                    _ => true, // default, may_do_yes, keep_all_on_top, send_all_to_graveyard, pick_top
                };
                if say_yes {
                    // I61: route via the controller-aware variant so
                    // controller-of-effect arms (DrawCards / GainLife /
                    // future) read the source's controller, not
                    // state.active_player. See docs/RUST_PARITY_GAPS.md
                    // I61 for the motivation.
                    crate::state_ops_resolve::apply_effect_pub_with_controller(
                        state,
                        &inner_effect,
                        source_obj_id,
                        controller,
                    )?;
                }
            }
            PendingDecision::PickCardFromExaminedChoice {
                controller, cards, ..
            } => {
                // "default" / "pick_top" → pick cards[0] (the topmost
                // popped — matches Python's no-agent-seated fallback
                // in LookTopNPutOneInHandRestToGraveyard.resolve).
                // Other strategies fall through to the same default
                // for robustness (a multi-variant queue should not
                // panic if drained with an unrelated strategy).
                resolve_pick_card_to_hand(state, controller, cards, /*chosen_idx*/ 0)?;
            }
            PendingDecision::ChooseModeChoice {
                source_obj_id,
                controller,
                modes,
            } => {
                // "default" / "choose_mode_0" → pick modes[0]. Other
                // strategies fall through to the same default for
                // robustness (matches Python's no-agent-seated
                // fallback in ModalChooseOne.resolve). An empty modes
                // Vec is a programmer error at the parse layer; if
                // it ever reaches here we drop the decision silently
                // rather than panic.
                if !modes.is_empty() {
                    // I61: route via the controller-aware variant so
                    // controller-of-effect arms inside the chosen mode
                    // see the source's controller.
                    crate::state_ops_resolve::apply_effect_pub_with_controller(
                        state,
                        &modes[0],
                        source_obj_id,
                        controller,
                    )?;
                }
            }
            PendingDecision::IfYouDoChoice {
                source_obj_id,
                controller,
                do_action,
                then_action,
            } => {
                // "default" / "if_you_do_yes" → apply both do_action
                // and then_action in order. "if_you_do_no" → drop
                // both. Other strategies fall through to "yes"
                // (matches Python's no-agent-seated default in
                // IfYouDo.resolve — MayDo says yes, both fire).
                let say_yes = match strategy {
                    "if_you_do_no" | "may_do_no" => false,
                    _ => true,
                };
                if say_yes {
                    // I61: controller-aware route for both inner
                    // actions so DrawCards / GainLife etc. resolve to
                    // the source's controller, not active_player.
                    crate::state_ops_resolve::apply_effect_pub_with_controller(
                        state,
                        &do_action,
                        source_obj_id,
                        controller,
                    )?;
                    crate::state_ops_resolve::apply_effect_pub_with_controller(
                        state,
                        &then_action,
                        source_obj_id,
                        controller,
                    )?;
                }
            }
            PendingDecision::ManifestDreadChoice {
                source_obj_id,
                controller,
                cards,
                then_attach_to_source,
                then_plus_one_counter_on_manifested,
                counter_amount,
            } => {
                // "default" / "manifest_top" → pick cards[0] (the
                // topmost popped — matches Python's no-agent-seated
                // fallback in ManifestDread.resolve, `manifest_id =
                // options[0]`). Other strategies fall through to the
                // same default for robustness.
                //
                // `then_attach_to_source` rider (round-29): after the
                // manifest routing, if true, stamp source.attached_to
                // = manifested_id. Silent partial if source LTB'd.
                //
                // `then_plus_one_counter_on_manifested` rider (round-29
                // ManifestDreadThenPutPlusOneCountersOnIt): after the
                // manifest routing, if true, stamp
                // `manifested.counters += counter_amount`. No-op when
                // cards was empty (no manifest happened).
                resolve_manifest_dread_to_battlefield(
                    state,
                    source_obj_id,
                    controller,
                    cards,
                    /*chosen_idx*/ 0,
                    then_attach_to_source,
                    then_plus_one_counter_on_manifested,
                    counter_amount,
                )?;
            }
            PendingDecision::OptionalManaCostChoice {
                source_obj_id,
                controller,
                cost,
                inner_effect,
            } => {
                // "optional_pay_no" → drop the decision unconditionally.
                // "optional_pay_yes" → REQUIRE affordability (raise on
                // unaffordable — programmer error to force-yes when
                // broke; the explicit strategy says "I expect this to
                // succeed").
                // "default" / unrelated → Python parity: pay-if-affordable,
                // else drop silently. Matches
                // OptionalManaCostThenEffect.resolve.
                match strategy {
                    "optional_pay_no" => {
                        // Drop; do nothing.
                    }
                    "optional_pay_yes" => {
                        if !pay_mana_cost_internal(state, controller, &cost) {
                            return Err(PyValueError::new_err(format!(
                                "auto_resolve_pending_decisions(\"optional_pay_yes\"): \
                                 controller P{controller} cannot afford cost {cost:?} \
                                 from mana pool {:?}",
                                state.players[controller as usize].mana_pool
                            )));
                        }
                        // I61: controller-aware route.
                        crate::state_ops_resolve::apply_effect_pub_with_controller(
                            state,
                            &inner_effect,
                            source_obj_id,
                            controller,
                        )?;
                    }
                    _ => {
                        // "default" / cross-strategy fallback: pay-if-
                        // affordable. Matches Python's no-agent-seated
                        // resolve.
                        if pay_mana_cost_internal(state, controller, &cost) {
                            // I61: controller-aware route.
                            crate::state_ops_resolve::apply_effect_pub_with_controller(
                                state,
                                &inner_effect,
                                source_obj_id,
                                controller,
                            )?;
                        }
                        // else: drop silently — matches Python's
                        // "trigger does nothing" fallback.
                    }
                }
            }
            PendingDecision::ScryChoice {
                controller, cards, ..
            } => {
                // "scry_send_bottom" → route the card to library bottom.
                // "default" / "scry_keep_top" → route to library top
                // (matches Python's no-agent-seated default — keeping
                // the top card is the conservative non-decision).
                // Unrelated strategies (e.g. "may_do_yes" on a mixed
                // queue) fall through to keep_top for robustness.
                let send_bottom = matches!(strategy, "scry_send_bottom");
                resolve_scry_with_keep_on_top(state, controller, cards, !send_bottom)?;
            }
            PendingDecision::LookAtTopNRevealOrCounterChoice {
                source_obj_id,
                controller,
                cards,
                filter_name,
                max_power,
                counter_on_miss,
            } => {
                // "reveal_yes" → pick the FIRST examined card that
                // matches the filter (`filter_name` + `max_power` for
                // the `"creature"` filter) and route it to hand; the
                // rest go to library bottom. No counter-on-miss rider
                // fires (a reveal happened).
                //
                // "default" / "reveal_no" / unrelated → no reveal; all
                // examined go to library bottom; fire counter-on-miss
                // rider if applicable + source still on bf.
                //
                // The Python class's no-agent-seated fallback IS the
                // no-reveal path (the agent-seated check at
                // `if options and p.agent is not None` guards the
                // reveal). So our "default" matches Python.
                let do_reveal_attempt = matches!(strategy, "reveal_yes");
                let pick_idx: Option<usize> = if do_reveal_attempt {
                    let mut idx: Option<usize> = None;
                    for (i, obj) in cards.iter().enumerate() {
                        if card_matches_filter(
                            state,
                            obj.printing_id,
                            &filter_name,
                            max_power,
                        ) {
                            idx = Some(i);
                            break;
                        }
                    }
                    idx
                } else {
                    None
                };
                match pick_idx {
                    Some(idx) => {
                        resolve_look_at_top_n_reveal_yes(
                            state,
                            controller,
                            cards,
                            idx,
                        )?;
                    }
                    None => {
                        resolve_look_at_top_n_reveal_no(
                            state,
                            controller,
                            source_obj_id,
                            cards,
                            counter_on_miss,
                        )?;
                    }
                }
            }
        }
    }
    Ok(())
}

/// Apply a "pick card to hand, rest to graveyard" decision.
/// Routes `cards[chosen_idx]` to controller's hand and every other
/// card to controller's graveyard, in popped order (cards[0] first if
/// it isn't the chosen, then cards[1] if it isn't the chosen, etc.).
fn resolve_pick_card_to_hand(
    state: &mut GameState,
    controller: u8,
    cards: Vec<GameObject>,
    chosen_idx: usize,
) -> PyResult<()> {
    if chosen_idx >= cards.len() {
        // Empty cards Vec or out-of-range chosen — empty pop is the
        // legitimate no-op path (library was empty). Out-of-range
        // chosen_idx is a programmer error; this is only ever called
        // with chosen_idx=0, so an empty cards Vec means we just
        // drop the decision silently. Surface as Ok(()) — matches
        // Python's empty-library short-circuit.
        return Ok(());
    }
    let pidx = controller as usize;
    let mut sorted_cards = cards;
    let chosen = sorted_cards.remove(chosen_idx);
    // Route chosen to hand.
    {
        let hand_mut: &mut Vec<GameObject> =
            Arc::make_mut(&mut state.players[pidx].hand);
        let mut obj = chosen;
        obj.zone = 0; // ZONE_HAND
        hand_mut.push(obj);
    }
    // Route the rest (preserving popped order) to graveyard.
    {
        let gy_mut: &mut Vec<GameObject> =
            Arc::make_mut(&mut state.players[pidx].graveyard);
        for mut obj in sorted_cards.into_iter() {
            obj.zone = 3; // ZONE_GRAVEYARD
            gy_mut.push(obj);
        }
    }
    Ok(())
}

/// Apply a ManifestDread decision. Routes `cards[chosen_idx]` to
/// the controller's battlefield (with standard ETB state reset) and
/// every other card to the controller's graveyard, in popped order.
///
/// **Face-down semantics — first-slice simplification.** The
/// manifested card lands on bf with its ORIGINAL printing visible
/// (name/types/P/T/abilities). Real MTG would set it to a 2/2
/// vanilla face-down creature (CR 701.34 + 707.2); modeling face-
/// down state requires either a face-down flag on GameObject
/// (forces fingerprint baseline rebuilding) or a face-down-
/// placeholder-printing approach — both deferred. See
/// SEARCH_LIMITATIONS.md.
///
/// **`then_attach_to_source` rider (round-29 ManifestDreadThenAttachSelf).**
/// After the manifest routing completes, if `then_attach_to_source`
/// is `true`, locate `source_obj_id` on its controller's battlefield
/// and stamp `source.attached_to = manifested_id`. If the source has
/// LTB'd between resolve-push and this submit (destroyed, returned to
/// hand, etc.), the attach step is a silent partial — manifest stays
/// applied, attach skipped. Mirrors Python's `manifested is None`
/// fall-through and the implicit "Equipment gone" path.
///
/// **`then_plus_one_counter_on_manifested` + `counter_amount` rider
/// (round-29 ManifestDreadThenPutPlusOneCountersOnIt).** After the
/// manifest routing completes, if the flag is `true`, stamp
/// `manifested.counters += counter_amount` on the just-manifested
/// permanent (located by the captured local `manifested_id`). When the
/// cards Vec was empty the early-return path skips both this and the
/// attach rider — mirrors Python's `if not new_ids: return` early-exit.
/// (We use the local `manifested_id` rather than a battlefield walk
/// for the counter step because we JUST routed the card to bf moments
/// ago — it's reachable on `state.players[pidx].battlefield` and
/// nothing else has had priority to remove it.)
///
/// Out-of-range `chosen_idx` or an empty cards Vec returns Ok(()) —
/// the empty case is the legitimate library-exhausted no-op path.
/// (When `then_attach_to_source` is true and the cards Vec is empty,
/// no manifested permanent exists so the attach step is naturally
/// skipped. Same for the counter step.)
fn resolve_manifest_dread_to_battlefield(
    state: &mut GameState,
    source_obj_id: u32,
    controller: u8,
    cards: Vec<GameObject>,
    chosen_idx: usize,
    then_attach_to_source: bool,
    then_plus_one_counter_on_manifested: bool,
    counter_amount: i32,
) -> PyResult<()> {
    if chosen_idx >= cards.len() {
        // Empty cards Vec (library was empty) → no-op success. No
        // manifested permanent → attach + counter steps naturally
        // no-op.
        return Ok(());
    }
    let pidx = controller as usize;
    let mut sorted_cards = cards;
    let chosen = sorted_cards.remove(chosen_idx);
    let manifested_id = chosen.id;
    // CE4 closure: reserve ETB timestamp before the player-mut borrow.
    let etb_ts = crate::state::reserve_etb_timestamp(state);
    // Route chosen to bf with the standard ETB state reset (mirrors
    // ReturnAllCreaturesFromYourGraveyardToBattlefield's reset).
    {
        let bf_mut: &mut Vec<GameObject> =
            Arc::make_mut(&mut state.players[pidx].battlefield);
        let mut obj = chosen;
        obj.zone = 2; // ZONE_BATTLEFIELD
        obj.tapped = false;
        obj.summoning_sick = true;
        obj.damage = 0;
        obj.counters = 0;
        obj.attached_to = None;
        obj.exiled_with_source = None;
        obj.controller = controller;
        obj.etb_timestamp = etb_ts;
        bf_mut.push(obj);
    }
    // ETB-trigger Slice 2 (RS12): queue + drain ENTERS for the
    // manifested face-down permanent. Mirrors Python's
    // `put_into_battlefield` / `_trigger_etb_abilities` on the
    // ManifestDread resolve path. Dispatch BEFORE the attach +
    // counter follow-ups so per-permanent ETB triggers see the
    // manifested object in its freshly-arrived state (no attach
    // relationship / no counter delta).
    state.pending_etb_dispatches.push(manifested_id);
    crate::state_ops_resolve::drain_pending_etb_dispatches(state)?;
    // Route the rest (preserving popped order) to graveyard.
    {
        let gy_mut: &mut Vec<GameObject> =
            Arc::make_mut(&mut state.players[pidx].graveyard);
        for mut obj in sorted_cards.into_iter() {
            obj.zone = 3; // ZONE_GRAVEYARD
            gy_mut.push(obj);
        }
    }
    // Round-29 ManifestDreadThenAttachSelf attach follow-up. Locate
    // source on ANY player's bf (the Equipment's controller may have
    // changed in pathological cases; common-case is `controller`).
    // Silent partial if source has LTB'd — mirrors Python's
    // `manifested is None: return` and the implicit "Equipment off
    // bf" fall-through.
    if then_attach_to_source {
        let mut src_player_idx: Option<usize> = None;
        for (pidx, player) in state.players.iter().enumerate() {
            if player.battlefield.iter().any(|o| o.id == source_obj_id) {
                src_player_idx = Some(pidx);
                break;
            }
        }
        if let Some(spidx) = src_player_idx {
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[spidx].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == source_obj_id {
                    obj.attached_to = Some(manifested_id);
                    break;
                }
            }
        }
        // else: source LTB'd → silent partial (manifest already done).
    }
    // Round-29 ManifestDreadThenPutPlusOneCountersOnIt counter follow-up.
    // The manifested permanent was just routed to bf on
    // state.players[pidx].battlefield; locate it by the captured
    // `manifested_id` and stamp `counters += counter_amount`. Net-i32
    // counter model: positive delta = N net +1/+1 counters (per
    // state_ops_counters.rs).
    if then_plus_one_counter_on_manifested && counter_amount != 0 {
        let bf_mut: &mut Vec<GameObject> =
            Arc::make_mut(&mut state.players[pidx].battlefield);
        for obj in bf_mut.iter_mut() {
            if obj.id == manifested_id {
                obj.counters += counter_amount;
                break;
            }
        }
    }
    Ok(())
}

/// Whether the printing with `printing_id` matches `filter_name`
/// per Python's `LookAtTopNRevealOrCounter._matches`:
/// - `"spacecraft"`: any Spacecraft card (currently approximated by
///   checking `card_types` for `"Spacecraft"` or subtypes carrying
///   the string — Rust printings don't yet track subtypes, so today
///   we accept only an exact `"Spacecraft"` card_type entry).
/// - `"creature"`: any Creature; with `max_power > 0`, additionally
///   require `printed_power <= max_power`. Living Phone shape.
/// - `"artifact"`: any Artifact.
///
/// Unknown filter strings return false (defensive — parse_effect
/// already rejects them).
pub(crate) fn card_matches_filter(
    state: &crate::state::GameState,
    printing_id: u32,
    filter_name: &str,
    max_power: i32,
) -> bool {
    let printing = match state.registry.lookup(printing_id) {
        Some(p) => p,
        None => return false,
    };
    match filter_name {
        "spacecraft" => {
            // Rust's CardPrinting carries only `card_types`. Real
            // Spacecraft cards have card_type == "Spacecraft" (a
            // top-level type, not a subtype) — first-slice match
            // mirrors that.
            printing.card_types.iter().any(|t| t == "Spacecraft")
        }
        "creature" => {
            let is_creature = printing.card_types.iter().any(|t| t == "Creature");
            if !is_creature {
                return false;
            }
            if max_power > 0 {
                match printing.power {
                    Some(p) => (p as i32) <= max_power,
                    None => false, // no printed power → can't satisfy a cap
                }
            } else {
                true
            }
        }
        "artifact" => printing.card_types.iter().any(|t| t == "Artifact"),
        _ => false,
    }
}

/// Apply a "reveal yes" submit: route `cards[chosen_idx]` to the
/// controller's hand; route every other examined card to the BOTTOM
/// of the controller's library (preserving popped order: cards[0],
/// then cards[1], etc.). No counter-on-miss rider fires.
fn resolve_look_at_top_n_reveal_yes(
    state: &mut GameState,
    controller: u8,
    cards: Vec<GameObject>,
    chosen_idx: usize,
) -> PyResult<()> {
    if chosen_idx >= cards.len() {
        // Empty cards (library exhausted) — fall through silently.
        return Ok(());
    }
    let pidx = controller as usize;
    let mut sorted_cards = cards;
    let chosen = sorted_cards.remove(chosen_idx);
    // Route chosen to hand.
    {
        let hand_mut: &mut Vec<GameObject> =
            Arc::make_mut(&mut state.players[pidx].hand);
        let mut obj = chosen;
        obj.zone = 0; // ZONE_HAND
        hand_mut.push(obj);
    }
    // Route the rest to library BOTTOM. Post-CE3 convention:
    // bottom = tail of Vec. Iterate in REVERSE popped-order and
    // push each: the last-pushed (cards[0], the topmost popped)
    // ends up at lib[len-1] = very bottom; cards[-1] (the deepest
    // popped) ends up at the highest of the bottomed batch.
    // Preserves the "cards[0] ends up DEEPEST" contract from the
    // pre-CE3 implementation (a deterministic mirror of the
    // "random order" rider — see SEARCH_LIMITATIONS).
    {
        let lib_mut: &mut Vec<GameObject> =
            Arc::make_mut(&mut state.players[pidx].library);
        for mut obj in sorted_cards.into_iter().rev() {
            obj.zone = 1; // ZONE_LIBRARY
            lib_mut.push(obj);
        }
    }
    Ok(())
}

/// Apply a "reveal no" submit: route ALL examined cards to the
/// BOTTOM of the controller's library (in popped order). If
/// `counter_on_miss` is true AND the source is on the battlefield,
/// add a +1/+1 counter to the source.
fn resolve_look_at_top_n_reveal_no(
    state: &mut GameState,
    controller: u8,
    source_obj_id: u32,
    cards: Vec<GameObject>,
    counter_on_miss: bool,
) -> PyResult<()> {
    let pidx = controller as usize;
    // Bottom in popped order (cards[0] → deepest, cards[-1] →
    // just above it). Post-CE3: bottom = tail; iterate reverse
    // and push so the last push (= cards[0]) lands at lib[len-1].
    {
        let lib_mut: &mut Vec<GameObject> =
            Arc::make_mut(&mut state.players[pidx].library);
        for mut obj in cards.into_iter().rev() {
            obj.zone = 1; // ZONE_LIBRARY
            lib_mut.push(obj);
        }
    }
    // Counter-on-miss rider: if `counter_on_miss` is true and source
    // is currently on some battlefield (Python checks
    // `source in state.battlefield`), add +1/+1 counter. If source
    // isn't on bf (still on stack, or destroyed in response), silent
    // no-op — Python parity.
    if counter_on_miss {
        let mut found_pidx: Option<usize> = None;
        for (pi, player) in state.players.iter().enumerate() {
            if player.battlefield.iter().any(|o| o.id == source_obj_id) {
                found_pidx = Some(pi);
                break;
            }
        }
        if let Some(spi) = found_pidx {
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[spi].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == source_obj_id {
                    obj.counters = obj.counters.saturating_add(1);
                    break;
                }
            }
        }
    }
    Ok(())
}

/// Apply the named strategy to a `SurveilChoice`'s observed cards.
/// Pure mutator on `state.players[controller]`.
fn resolve_surveil_with_strategy(
    state: &mut GameState,
    controller: u8,
    cards: Vec<GameObject>,
    strategy: &str,
) -> PyResult<()> {
    match strategy {
        "keep_all_on_top" => {
            // Return cards to library top in popped order. cards[0]
            // was popped FIRST (it was the topmost card). Post-CE3:
            // top = lib[0]. To restore the original ordering, insert
            // each at lib[0] in REVERSE popped-order: the last
            // insert (cards[0]) lands at lib[0] = top; cards[1]
            // becomes lib[1]; etc. After the loop, the popped block
            // sits at lib[..n] in original popped order — identical
            // to the pre-Surveil library shape.
            let pidx = controller as usize;
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            for obj in cards.into_iter().rev() {
                lib_mut.insert(0, obj);
            }
            Ok(())
        }
        "send_all_to_graveyard" => {
            let pidx = controller as usize;
            let gy_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].graveyard);
            for mut obj in cards.into_iter() {
                // Rewrite zone tag to graveyard before pushing.
                // ZONE_GRAVEYARD = 3 (per state_ops_zones).
                obj.zone = 3;
                gy_mut.push(obj);
            }
            Ok(())
        }
        other => Err(PyValueError::new_err(format!(
            "auto_resolve_pending_decisions: unknown strategy {other:?}; \
             valid strategies: keep_all_on_top, send_all_to_graveyard"
        ))),
    }
}

/// Round-30 G24 closure — Paris scry-on-keep routing helper. Routes
/// the single examined card carried by a `ScryChoice` either to the
/// top of the controller's library (when `keep_on_top=true`) or to
/// the bottom of the library (when `keep_on_top=false`).
///
/// Pure mutator on `state.players[controller].library`. An empty
/// `cards` Vec (defensive: library was empty when `keep_hand` ran)
/// is a silent no-op.
fn resolve_scry_with_keep_on_top(
    state: &mut GameState,
    controller: u8,
    cards: Vec<GameObject>,
    keep_on_top: bool,
) -> PyResult<()> {
    if cards.is_empty() {
        // Empty pre-popped card list — defensive no-op (library was
        // empty when keep_hand ran).
        return Ok(());
    }
    let pidx = controller as usize;
    let lib_mut: &mut Vec<GameObject> =
        Arc::make_mut(&mut state.players[pidx].library);
    for mut obj in cards.into_iter() {
        obj.zone = 1; // ZONE_LIBRARY
        if keep_on_top {
            // Library top = lib[0] (post-CE3).
            lib_mut.insert(0, obj);
        } else {
            // Library bottom = tail of the Vec (post-CE3).
            lib_mut.push(obj);
        }
    }
    Ok(())
}

#[pymethods]
impl GameState {
    /// Whether any `PendingDecision` is currently waiting for the
    /// caller to resolve. `True` after a Surveil arm ran via
    /// `resolve_top_of_stack_pause`; `False` after a normal
    /// `resolve_top_of_stack` (which auto-resolves).
    fn has_pending_decision(&self) -> bool {
        !self.pending_decisions.is_empty()
    }

    /// Snapshot the pending-decisions queue as a list of dicts.
    /// Each dict carries `kind` (the variant tag — currently only
    /// `"SurveilChoice"`) plus variant-specific keys:
    ///
    /// * `SurveilChoice`: `source_obj_id` (u32), `controller` (u8),
    ///   `cards` (list of u32 — the observed card ids, top-most
    ///   first).
    ///
    /// Returns a NEW list — mutating the returned list does not
    /// affect the queue. To consume use `submit_surveil_decision`
    /// or `auto_resolve_pending_decisions`.
    fn pending_decisions<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyList>> {
        let out = PyList::empty(py);
        for decision in &self.pending_decisions {
            let d = PyDict::new(py);
            match decision {
                PendingDecision::SurveilChoice {
                    source_obj_id,
                    controller,
                    cards,
                } => {
                    d.set_item("kind", "SurveilChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    let card_ids: Vec<u32> = cards.iter().map(|o| o.id).collect();
                    d.set_item("cards", card_ids)?;
                }
                PendingDecision::MayDoChoice {
                    source_obj_id,
                    controller,
                    inner_effect,
                } => {
                    d.set_item("kind", "MayDoChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    // Surface the inner effect kind as a string for
                    // dict consumers (debug / parity introspection).
                    // The actual inner_effect lives only in the
                    // pending_decisions Vec; the dict is a snapshot.
                    let inner_dict = crate::cards::effect_to_pydict(py, inner_effect.as_ref())?;
                    d.set_item("inner_effect", inner_dict)?;
                }
                PendingDecision::PickCardFromExaminedChoice {
                    source_obj_id,
                    controller,
                    cards,
                } => {
                    d.set_item("kind", "PickCardFromExaminedChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    let card_ids: Vec<u32> = cards.iter().map(|o| o.id).collect();
                    d.set_item("cards", card_ids)?;
                }
                PendingDecision::ChooseModeChoice {
                    source_obj_id,
                    controller,
                    modes,
                } => {
                    d.set_item("kind", "ChooseModeChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    // Surface each mode's full Effect dict so agents
                    // can inspect the choice surface. List position
                    // == mode index for submit_choose_mode_decision.
                    let mode_dicts: Vec<Bound<'_, PyDict>> = modes
                        .iter()
                        .map(|m| crate::cards::effect_to_pydict(py, m))
                        .collect::<PyResult<Vec<_>>>()?;
                    d.set_item("modes", mode_dicts)?;
                }
                PendingDecision::IfYouDoChoice {
                    source_obj_id,
                    controller,
                    do_action,
                    then_action,
                } => {
                    d.set_item("kind", "IfYouDoChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    let do_dict = crate::cards::effect_to_pydict(py, do_action.as_ref())?;
                    let then_dict = crate::cards::effect_to_pydict(py, then_action.as_ref())?;
                    d.set_item("do_action", do_dict)?;
                    d.set_item("then_action", then_dict)?;
                }
                PendingDecision::ManifestDreadChoice {
                    source_obj_id,
                    controller,
                    cards,
                    then_attach_to_source,
                    then_plus_one_counter_on_manifested,
                    counter_amount,
                } => {
                    d.set_item("kind", "ManifestDreadChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    let card_ids: Vec<u32> = cards.iter().map(|o| o.id).collect();
                    d.set_item("cards", card_ids)?;
                    d.set_item("then_attach_to_source", *then_attach_to_source)?;
                    d.set_item(
                        "then_plus_one_counter_on_manifested",
                        *then_plus_one_counter_on_manifested,
                    )?;
                    d.set_item("counter_amount", *counter_amount)?;
                }
                PendingDecision::LookAtTopNRevealOrCounterChoice {
                    source_obj_id,
                    controller,
                    cards,
                    filter_name,
                    max_power,
                    counter_on_miss,
                } => {
                    d.set_item("kind", "LookAtTopNRevealOrCounterChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    let card_ids: Vec<u32> = cards.iter().map(|o| o.id).collect();
                    d.set_item("cards", card_ids)?;
                    d.set_item("filter_name", filter_name.as_str())?;
                    d.set_item("max_power", *max_power)?;
                    d.set_item("counter_on_miss", *counter_on_miss)?;
                }
                PendingDecision::OptionalManaCostChoice {
                    source_obj_id,
                    controller,
                    cost,
                    inner_effect,
                } => {
                    d.set_item("kind", "OptionalManaCostChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    // Cost surfaces as a mana-cost-shape dict, matching
                    // the schema used in `Effect::OptionalManaCostThenEffect`'s
                    // dict serialization.
                    let cost_dict = PyDict::new(py);
                    if cost.generic > 0 {
                        cost_dict.set_item("generic", cost.generic)?;
                    }
                    if cost.white > 0 {
                        cost_dict.set_item("W", cost.white)?;
                    }
                    if cost.blue > 0 {
                        cost_dict.set_item("U", cost.blue)?;
                    }
                    if cost.black > 0 {
                        cost_dict.set_item("B", cost.black)?;
                    }
                    if cost.red > 0 {
                        cost_dict.set_item("R", cost.red)?;
                    }
                    if cost.green > 0 {
                        cost_dict.set_item("G", cost.green)?;
                    }
                    d.set_item("cost", cost_dict)?;
                    let inner_dict = crate::cards::effect_to_pydict(py, inner_effect.as_ref())?;
                    d.set_item("inner_effect", inner_dict)?;
                }
                PendingDecision::ScryChoice {
                    source_obj_id,
                    controller,
                    cards,
                } => {
                    // Round-30 G24 closure: same dict shape as
                    // SurveilChoice / PickCardFromExaminedChoice — the
                    // examined card list is a flat list of u32 ids. With
                    // a non-empty library at keep_hand time, len == 1
                    // (Paris scry-1); with an empty library, len == 0.
                    d.set_item("kind", "ScryChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    let card_ids: Vec<u32> = cards.iter().map(|o| o.id).collect();
                    d.set_item("cards", card_ids)?;
                }
            }
            out.append(d)?;
        }
        Ok(out)
    }

    /// Consume the head `SurveilChoice` on the pending-decisions
    /// queue: route `card_ids_to_top` back onto the controller's
    /// library top (preserving the given order — the first id in
    /// the list ends up as the topmost card; subsequent ids land
    /// one position deeper), and route `card_ids_to_graveyard` into
    /// the controller's graveyard (in the given order).
    ///
    /// Every id in the SurveilChoice's `cards` must appear in
    /// EXACTLY ONE of the two lists; an id that's missing or that
    /// appears in both raises `ValueError`. An id that references a
    /// card NOT in the pending SurveilChoice also raises
    /// `ValueError`. The submitted-vs-pending check is done before
    /// any mutation, so a failed submit leaves the state untouched
    /// (transactional shape).
    ///
    /// Raises `ValueError` if the queue is empty or its head is not
    /// a SurveilChoice.
    fn submit_surveil_decision(
        &mut self,
        card_ids_to_top: Vec<u32>,
        card_ids_to_graveyard: Vec<u32>,
    ) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_surveil_decision: no pending decision",
            ));
        }
        // Inspect (don't pop yet) so a validation failure leaves
        // the queue intact.
        let (source_obj_id, controller, cards) = match &self.pending_decisions[0] {
            PendingDecision::SurveilChoice {
                source_obj_id,
                controller,
                cards,
            } => (*source_obj_id, *controller, cards.clone()),
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_surveil_decision: head of pending-decisions queue is \
                     not a SurveilChoice (got {:?}); call the variant-specific \
                     submit_* dispatcher (e.g. submit_may_do_decision)",
                    std::mem::discriminant(other)
                )));
            }
        };
        let _ = source_obj_id; // recorded for log-correlation; not used in routing

        // Validation: every pending id must appear exactly once
        // across the two submitted lists; no submitted id may
        // reference a card not in the pending set.
        let mut pending_ids: Vec<u32> = cards.iter().map(|o| o.id).collect();
        pending_ids.sort_unstable();
        let mut submitted: Vec<u32> = Vec::with_capacity(
            card_ids_to_top.len() + card_ids_to_graveyard.len(),
        );
        submitted.extend_from_slice(&card_ids_to_top);
        submitted.extend_from_slice(&card_ids_to_graveyard);
        submitted.sort_unstable();
        if pending_ids != submitted {
            return Err(PyValueError::new_err(format!(
                "submit_surveil_decision: submitted ids {:?} do not match \
                 pending SurveilChoice ids {:?}",
                {
                    let mut s = card_ids_to_top.clone();
                    s.extend_from_slice(&card_ids_to_graveyard);
                    s
                },
                cards.iter().map(|o| o.id).collect::<Vec<u32>>(),
            )));
        }

        // Validation passed — now consume the head and apply.
        self.pending_decisions.remove(0);
        let pidx = controller as usize;

        // Route to graveyard first (order matches submission).
        {
            let gy_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut self.players[pidx].graveyard);
            for id in &card_ids_to_graveyard {
                let mut obj = cards
                    .iter()
                    .find(|o| o.id == *id)
                    .cloned()
                    .expect("validation guarantees membership");
                obj.zone = 3; // ZONE_GRAVEYARD
                gy_mut.push(obj);
            }
        }
        // Route to library top. The submitted order determines
        // depth: card_ids_to_top[0] is the topmost (lib[0] post-
        // CE3), card_ids_to_top[1] is second-from-top, etc. So
        // insert each at lib[0] in REVERSE submitted order: the
        // last insert (card_ids_to_top[0]) lands at lib[0] = top;
        // card_ids_to_top[1] becomes lib[1]; etc.
        {
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut self.players[pidx].library);
            for id in card_ids_to_top.iter().rev() {
                let mut obj = cards
                    .iter()
                    .find(|o| o.id == *id)
                    .cloned()
                    .expect("validation guarantees membership");
                obj.zone = 1; // ZONE_LIBRARY
                lib_mut.insert(0, obj);
            }
        }
        Ok(())
    }

    /// Consume the head `MayDoChoice` on the pending-decisions queue
    /// with a `yes`/`no` answer. On `yes`, the inner effect carried
    /// by the variant is applied via the standard `apply_effect`
    /// dispatcher (with `source_obj_id` propagated so the inner
    /// retains the resolving spell's identity for "you may" prompts
    /// like Lithobraking's "if you do, ..." rider). On `no`, the
    /// variant is dropped without any inner application.
    ///
    /// Transactional shape: validation runs before any mutation, so
    /// a failed submit leaves the queue intact (matching
    /// `submit_surveil_decision`).
    ///
    /// Raises `ValueError` if the queue is empty or its head is not
    /// a `MayDoChoice`.
    fn submit_may_do_decision(&mut self, yes: bool) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_may_do_decision: no pending decision",
            ));
        }
        // Inspect head (don't pop yet) so the discriminant check
        // doesn't disturb the queue on failure.
        match &self.pending_decisions[0] {
            PendingDecision::MayDoChoice { .. } => {}
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_may_do_decision: head of pending-decisions queue is \
                     not a MayDoChoice (got {:?}); call the variant-specific \
                     submit_* dispatcher (e.g. submit_surveil_decision)",
                    std::mem::discriminant(other)
                )));
            }
        }
        // Validation passed — consume the head.
        let decision = self.pending_decisions.remove(0);
        let (source_obj_id, controller, inner_effect) = match decision {
            PendingDecision::MayDoChoice {
                source_obj_id,
                controller,
                inner_effect,
            } => (source_obj_id, controller, inner_effect),
            // Unreachable: we just validated head was MayDoChoice
            // above. The pattern is here for the irrefutable-match
            // shape only.
            _ => unreachable!("validated above"),
        };
        if yes {
            // I61: route via the controller-aware variant. Latent today
            // (current EoE printings have active_player == source
            // controller in the test suite), but cross-controller MayDo
            // resolution must thread the source's controller through to
            // DrawCards / GainLife / future controller-of-effect arms.
            crate::state_ops_resolve::apply_effect_pub_with_controller(
                self,
                &inner_effect,
                source_obj_id,
                controller,
            )?;
        }
        Ok(())
    }

    /// Consume the head `PickCardFromExaminedChoice` on the pending-
    /// decisions queue: route `chosen_id` to the controller's hand and
    /// every other examined card to the controller's graveyard (in
    /// popped order). `chosen_id` MUST be one of the examined card
    /// ids; an unknown id raises `ValueError` transactionally (no
    /// mutation on failure).
    ///
    /// Powers the round-28 `LookTopNPutOneInHandRestToGraveyard`
    /// Effect (Commune-with-Evil family). The dispatcher mirrors
    /// Python's `LookTopNPutOneInHandRestToGraveyard.resolve`: the
    /// chosen card is moved to hand and revealed to all (the latter
    /// is a Python-side log/observability feature with no Rust
    /// surface yet); the rest go to graveyard in popped order.
    ///
    /// Raises `ValueError` if the queue is empty, its head is not a
    /// `PickCardFromExaminedChoice`, or `chosen_id` is not one of the
    /// examined ids.
    fn submit_pick_card_decision(&mut self, chosen_id: u32) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_pick_card_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation on a discriminant
        // mismatch or unknown chosen_id.
        let chosen_idx = match &self.pending_decisions[0] {
            PendingDecision::PickCardFromExaminedChoice { cards, .. } => {
                let idx = cards.iter().position(|o| o.id == chosen_id);
                match idx {
                    Some(i) => i,
                    None => {
                        return Err(PyValueError::new_err(format!(
                            "submit_pick_card_decision: chosen_id {chosen_id} \
                             is not one of the examined card ids {:?}",
                            cards.iter().map(|o| o.id).collect::<Vec<u32>>()
                        )));
                    }
                }
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_pick_card_decision: head of pending-decisions queue is \
                     not a PickCardFromExaminedChoice (got {:?}); call the \
                     variant-specific submit_* dispatcher (e.g. \
                     submit_surveil_decision, submit_may_do_decision)",
                    std::mem::discriminant(other)
                )));
            }
        };
        // Validation passed — consume the head and route.
        let decision = self.pending_decisions.remove(0);
        let (controller, cards) = match decision {
            PendingDecision::PickCardFromExaminedChoice {
                controller, cards, ..
            } => (controller, cards),
            _ => unreachable!("validated above"),
        };
        resolve_pick_card_to_hand(self, controller, cards, chosen_idx)
    }

    /// Consume the head `ChooseModeChoice` on the pending-decisions
    /// queue: apply `modes[chosen_idx]` via the standard
    /// `apply_effect` dispatcher (with the original `source_obj_id`
    /// propagated so identity-coupled riders retain identity).
    /// `chosen_idx` MUST be a valid index into `modes`; out-of-range
    /// raises `ValueError` transactionally (no mutation on failure).
    ///
    /// Powers the round-28 `Effect::ChooseOneMode` wrapper. Mirrors
    /// Python's `ModalChooseOne.resolve` for the resolve-time-pick
    /// shape (cast-time mode picking via `state.resolving_modes` is
    /// deferred).
    ///
    /// Raises `ValueError` if the queue is empty, its head is not a
    /// `ChooseModeChoice`, or `chosen_idx` is out of range.
    fn submit_choose_mode_decision(&mut self, chosen_idx: usize) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_choose_mode_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation on a discriminant
        // mismatch or out-of-range index.
        match &self.pending_decisions[0] {
            PendingDecision::ChooseModeChoice { modes, .. } => {
                if chosen_idx >= modes.len() {
                    return Err(PyValueError::new_err(format!(
                        "submit_choose_mode_decision: chosen_idx {chosen_idx} \
                         out of range for {} modes",
                        modes.len()
                    )));
                }
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_choose_mode_decision: head of pending-decisions queue is \
                     not a ChooseModeChoice (got {:?}); call the variant-specific \
                     submit_* dispatcher (e.g. submit_surveil_decision, \
                     submit_may_do_decision, submit_pick_card_decision)",
                    std::mem::discriminant(other)
                )));
            }
        }
        // Validation passed — consume the head.
        let decision = self.pending_decisions.remove(0);
        let (source_obj_id, controller, modes) = match decision {
            PendingDecision::ChooseModeChoice {
                source_obj_id,
                controller,
                modes,
            } => (source_obj_id, controller, modes),
            _ => unreachable!("validated above"),
        };
        // I61: controller-aware route — the chosen mode's inner effects
        // must read the source's controller for controller-of-effect
        // arms (DrawCards / GainLife / ...).
        crate::state_ops_resolve::apply_effect_pub_with_controller(
            self,
            &modes[chosen_idx],
            source_obj_id,
            controller,
        )
    }

    /// Consume the head `IfYouDoChoice` on the pending-decisions
    /// queue with a `yes`/`no` answer. On `yes`, both `do_action` and
    /// `then_action` are applied (in order) via the standard
    /// `apply_effect` dispatcher with the original `source_obj_id`.
    /// On `no`, neither is applied.
    ///
    /// Powers the round-28 `Effect::IfYouDo` wrapper. First-slice
    /// shape: the do_action is assumed to be implicitly success-on-
    /// yes (i.e. IfYouDo(MayDo(X), Y) form). General "did do_action
    /// signal failure" plumbing is deferred to a future slice.
    ///
    /// Raises `ValueError` if the queue is empty or its head is not
    /// an `IfYouDoChoice`. Transactional shape — validation runs
    /// before any mutation.
    fn submit_if_you_do_decision(&mut self, yes: bool) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_if_you_do_decision: no pending decision",
            ));
        }
        match &self.pending_decisions[0] {
            PendingDecision::IfYouDoChoice { .. } => {}
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_if_you_do_decision: head of pending-decisions queue is \
                     not an IfYouDoChoice (got {:?}); call the variant-specific \
                     submit_* dispatcher",
                    std::mem::discriminant(other)
                )));
            }
        }
        let decision = self.pending_decisions.remove(0);
        let (source_obj_id, controller, do_action, then_action) = match decision {
            PendingDecision::IfYouDoChoice {
                source_obj_id,
                controller,
                do_action,
                then_action,
            } => (source_obj_id, controller, do_action, then_action),
            _ => unreachable!("validated above"),
        };
        if yes {
            // I61: controller-aware route for both inner actions.
            crate::state_ops_resolve::apply_effect_pub_with_controller(
                self,
                &do_action,
                source_obj_id,
                controller,
            )?;
            crate::state_ops_resolve::apply_effect_pub_with_controller(
                self,
                &then_action,
                source_obj_id,
                controller,
            )?;
        }
        Ok(())
    }

    /// Consume the head `ManifestDreadChoice` on the pending-
    /// decisions queue: route `chosen_id` to the controller's
    /// battlefield (with the standard ETB state reset:
    /// summoning_sick=true, tapped=false, damage=0, counters=0,
    /// attached_to=None, exiled_with_source=None) and every other
    /// examined card to the controller's graveyard (in popped
    /// order). `chosen_id` MUST be one of the examined card ids;
    /// an unknown id raises `ValueError` transactionally (no
    /// mutation on failure).
    ///
    /// Powers the round-28 `Effect::ManifestDread` wrapper (Bashful-
    /// Beastie family, 10 EoE cards — highest-frequency previously-
    /// unported class). The dispatcher mirrors Python's
    /// `ManifestDread.resolve`: the chosen card is moved to bf as a
    /// "face-down" creature (first-slice simplification: original
    /// printing remains visible — see SEARCH_LIMITATIONS.md); the
    /// rest go to graveyard in popped order.
    ///
    /// Raises `ValueError` if the queue is empty, its head is not a
    /// `ManifestDreadChoice`, or `chosen_id` is not one of the
    /// examined ids.
    fn submit_manifest_dread_decision(&mut self, chosen_id: u32) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_manifest_dread_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation on a discriminant
        // mismatch or unknown chosen_id.
        let chosen_idx = match &self.pending_decisions[0] {
            PendingDecision::ManifestDreadChoice { cards, .. } => {
                let idx = cards.iter().position(|o| o.id == chosen_id);
                match idx {
                    Some(i) => i,
                    None => {
                        return Err(PyValueError::new_err(format!(
                            "submit_manifest_dread_decision: chosen_id {chosen_id} \
                             is not one of the examined card ids {:?}",
                            cards.iter().map(|o| o.id).collect::<Vec<u32>>()
                        )));
                    }
                }
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_manifest_dread_decision: head of pending-decisions queue is \
                     not a ManifestDreadChoice (got {:?}); call the \
                     variant-specific submit_* dispatcher",
                    std::mem::discriminant(other)
                )));
            }
        };
        // Validation passed — consume the head and route.
        let decision = self.pending_decisions.remove(0);
        let (
            source_obj_id,
            controller,
            cards,
            then_attach_to_source,
            then_plus_one_counter_on_manifested,
            counter_amount,
        ) = match decision {
            PendingDecision::ManifestDreadChoice {
                source_obj_id,
                controller,
                cards,
                then_attach_to_source,
                then_plus_one_counter_on_manifested,
                counter_amount,
            } => (
                source_obj_id,
                controller,
                cards,
                then_attach_to_source,
                then_plus_one_counter_on_manifested,
                counter_amount,
            ),
            _ => unreachable!("validated above"),
        };
        resolve_manifest_dread_to_battlefield(
            self,
            source_obj_id,
            controller,
            cards,
            chosen_idx,
            then_attach_to_source,
            then_plus_one_counter_on_manifested,
            counter_amount,
        )
    }

    /// Consume the head `LookAtTopNRevealOrCounterChoice` on the
    /// pending-decisions queue.
    ///
    /// On `reveal=True`, `chosen_id` MUST be supplied (not None) and
    /// must:
    /// 1. Be one of the examined card ids on the head variant.
    /// 2. Match the variant's `filter_name` (and `max_power` cap for
    ///    the `"creature"` filter) — Python's `_matches` check.
    ///
    /// The chosen card moves to the controller's HAND; the rest go
    /// to the BOTTOM of the controller's library in popped order
    /// (first-slice simplification — see
    /// `Effect::LookAtTopNRevealOrCounter` docstring on the
    /// "random order" deferred work). No counter-on-miss rider
    /// fires (a card was revealed).
    ///
    /// On `reveal=False`, `chosen_id` is ignored (pass any u32 — `0`
    /// is the conventional sentinel). ALL examined cards go to the
    /// library bottom in popped order. If the variant's
    /// `counter_on_miss` is true AND the source is on the battlefield,
    /// a +1/+1 counter lands on the source. Source-not-on-bf is a
    /// silent no-op for the counter rider (matches Python's
    /// `source in state.battlefield` check).
    ///
    /// Transactional shape: validation runs before any mutation; a
    /// failed submit leaves the queue intact.
    ///
    /// Raises `ValueError` if:
    /// - the queue is empty
    /// - the head is not a `LookAtTopNRevealOrCounterChoice`
    /// - `reveal=True` and `chosen_id` is not one of the examined ids
    /// - `reveal=True` and the chosen card's printing doesn't match
    ///   the filter
    #[pyo3(signature = (reveal, chosen_id=None))]
    fn submit_look_at_top_n_decision(
        &mut self,
        reveal: bool,
        chosen_id: Option<u32>,
    ) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_look_at_top_n_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation.
        let chosen_idx: Option<usize> = match &self.pending_decisions[0] {
            PendingDecision::LookAtTopNRevealOrCounterChoice {
                cards,
                filter_name,
                max_power,
                ..
            } => {
                if reveal {
                    let cid = chosen_id.ok_or_else(|| {
                        PyValueError::new_err(
                            "submit_look_at_top_n_decision: reveal=True requires \
                             chosen_id (got None)",
                        )
                    })?;
                    let idx = cards.iter().position(|o| o.id == cid).ok_or_else(|| {
                        PyValueError::new_err(format!(
                            "submit_look_at_top_n_decision: chosen_id {cid} is not \
                             one of the examined card ids {:?}",
                            cards.iter().map(|o| o.id).collect::<Vec<u32>>()
                        ))
                    })?;
                    // Filter check.
                    let obj = &cards[idx];
                    if !card_matches_filter(self, obj.printing_id, filter_name, *max_power) {
                        return Err(PyValueError::new_err(format!(
                            "submit_look_at_top_n_decision: chosen card (id {cid}, \
                             printing_id {}) does not match filter {filter_name:?} \
                             (max_power={max_power})",
                            obj.printing_id
                        )));
                    }
                    Some(idx)
                } else {
                    None
                }
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_look_at_top_n_decision: head of pending-decisions queue is \
                     not a LookAtTopNRevealOrCounterChoice (got {:?}); call the \
                     variant-specific submit_* dispatcher",
                    std::mem::discriminant(other)
                )));
            }
        };
        // Validation passed — consume the head and route.
        let decision = self.pending_decisions.remove(0);
        let (source_obj_id, controller, cards, counter_on_miss) = match decision {
            PendingDecision::LookAtTopNRevealOrCounterChoice {
                source_obj_id,
                controller,
                cards,
                counter_on_miss,
                ..
            } => (source_obj_id, controller, cards, counter_on_miss),
            _ => unreachable!("validated above"),
        };
        match chosen_idx {
            Some(idx) => resolve_look_at_top_n_reveal_yes(self, controller, cards, idx),
            None => resolve_look_at_top_n_reveal_no(
                self,
                controller,
                source_obj_id,
                cards,
                counter_on_miss,
            ),
        }
    }

    /// Consume the head `OptionalManaCostChoice` on the pending-
    /// decisions queue with a `pay`/`skip` answer. On `pay=True`, the
    /// dispatcher validates that the controller can pay the variant's
    /// `cost` from their mana pool — if not, raises `ValueError`
    /// transactionally (no mutation; the pending decision stays at the
    /// head of the queue). On success, the cost is deducted from the
    /// pool atomically, then the inner effect is applied via the
    /// standard `apply_effect` dispatcher with the original
    /// `source_obj_id` propagated (so identity-coupled riders retain
    /// the resolving spell's identity). On `pay=False`, the variant
    /// is dropped without paying or applying the inner effect.
    ///
    /// Powers the round-29 `Effect::OptionalManaCostThenEffect`
    /// wrapper (Kavaron-Harrier / Oreplate-Pangolin "you may pay {1};
    /// if you do, ..." family, freq 2 in EoE pool).
    ///
    /// Transactional shape: validation runs before any mutation. A
    /// failed submit (queue empty, head not a OptionalManaCostChoice,
    /// or pay=True without enough mana) leaves the state intact.
    ///
    /// Raises `ValueError` if:
    /// - the queue is empty
    /// - the head is not a `OptionalManaCostChoice`
    /// - `pay=True` and the controller's mana pool can't cover the cost
    fn submit_optional_mana_cost_decision(&mut self, pay: bool) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_optional_mana_cost_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation on a discriminant
        // mismatch or an unaffordable pay=True.
        match &self.pending_decisions[0] {
            PendingDecision::OptionalManaCostChoice { cost, controller, .. } => {
                if pay && !can_pay_mana_cost_internal(self, *controller, cost) {
                    return Err(PyValueError::new_err(format!(
                        "submit_optional_mana_cost_decision: controller P{} cannot \
                         afford cost {cost:?} from mana pool {:?}",
                        controller,
                        self.players[*controller as usize].mana_pool
                    )));
                }
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_optional_mana_cost_decision: head of pending-decisions queue is \
                     not an OptionalManaCostChoice (got {:?}); call the \
                     variant-specific submit_* dispatcher",
                    std::mem::discriminant(other)
                )));
            }
        }
        // Validation passed — consume the head.
        let decision = self.pending_decisions.remove(0);
        let (source_obj_id, controller, cost, inner_effect) = match decision {
            PendingDecision::OptionalManaCostChoice {
                source_obj_id,
                controller,
                cost,
                inner_effect,
            } => (source_obj_id, controller, cost, inner_effect),
            _ => unreachable!("validated above"),
        };
        if pay {
            let ok = pay_mana_cost_internal(self, controller, &cost);
            // Belt-and-suspenders: validation above already confirmed
            // affordability — pay must succeed.
            debug_assert!(ok);
            // I61: controller-aware route — the inner effect's
            // controller-of-effect arms (DrawCards / GainLife / ...)
            // read the source's controller.
            crate::state_ops_resolve::apply_effect_pub_with_controller(
                self,
                &inner_effect,
                source_obj_id,
                controller,
            )?;
        }
        Ok(())
    }

    /// Round-30 G24 closure — submit a Paris scry-on-keep decision.
    /// Consumes the head `ScryChoice` on the pending-decisions queue:
    /// on `keep_on_top=true` the examined card returns to the
    /// controller's library top (lib[0]); on `keep_on_top=false` the
    /// examined card moves to the controller's library bottom (tail
    /// of the Vec).
    ///
    /// Powers the round-30 `GameState::keep_hand` flow. Mirrors
    /// CR 103.4 "scry 1" semantics: look at the top card, decide
    /// whether to keep it on top or send it to the bottom.
    ///
    /// **Empty-library partial.** If the variant was pushed with an
    /// empty `cards` Vec (library was empty at `keep_hand` time), the
    /// submit is a no-op that just consumes the head. Both
    /// `keep_on_top=true` and `keep_on_top=false` produce the same
    /// (empty) result.
    ///
    /// Transactional shape: validation runs before any mutation, so a
    /// failed submit (queue empty, head not a ScryChoice) leaves the
    /// state intact.
    ///
    /// Raises `ValueError` if:
    /// - the queue is empty
    /// - the head is not a `ScryChoice`
    fn submit_scry_decision(&mut self, keep_on_top: bool) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_scry_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation on a discriminant
        // mismatch.
        match &self.pending_decisions[0] {
            PendingDecision::ScryChoice { .. } => {}
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_scry_decision: head of pending-decisions queue is \
                     not a ScryChoice (got {:?}); call the variant-specific \
                     submit_* dispatcher (e.g. submit_surveil_decision)",
                    std::mem::discriminant(other)
                )));
            }
        }
        // Validation passed — consume the head.
        let decision = self.pending_decisions.remove(0);
        let (controller, cards) = match decision {
            PendingDecision::ScryChoice {
                controller, cards, ..
            } => (controller, cards),
            _ => unreachable!("validated above"),
        };
        resolve_scry_with_keep_on_top(self, controller, cards, keep_on_top)
    }

    /// Drain the pending-decisions queue using a deterministic
    /// strategy. Useful for callers that don't model the choice
    /// dimension (training harnesses, parity tests, deterministic
    /// regression scenarios).
    ///
    /// Strategies:
    /// * `"keep_all_on_top"` — Surveil returns every observed card
    ///   to the library top, preserving the order they were popped
    ///   (the r23 deterministic baseline behavior, bit-equal to the
    ///   pre-r27 path). MayDo answers "yes" (compatibility default).
    /// * `"send_all_to_graveyard"` — Surveil sends every observed
    ///   card to the controller's graveyard, in popped order. MayDo
    ///   answers "yes" (compatibility default).
    /// * `"may_do_yes"` — MayDo answers "yes" (apply inner effect).
    ///   Surveil falls through to `keep_all_on_top`.
    /// * `"may_do_no"` — MayDo answers "no" (drop inner effect).
    ///   Surveil falls through to `keep_all_on_top`.
    /// * `"pick_top"` — PickCardFromExamined picks the topmost
    ///   examined card (cards[0]). Other variants fall through to
    ///   their own per-variant defaults.
    /// * `"choose_mode_0"` — ChooseModeChoice picks `modes[0]`.
    ///   Other variants fall through to their own per-variant
    ///   defaults.
    /// * `"if_you_do_yes"` — IfYouDoChoice applies both do_action
    ///   and then_action. Other variants fall through to their own
    ///   per-variant defaults.
    /// * `"if_you_do_no"` — IfYouDoChoice drops both. MayDo also
    ///   answers "no" (shared yes/no semantics).
    /// * `"optional_pay_yes"` — OptionalManaCostChoice pays the cost
    ///   and applies the inner effect; raises `ValueError` if the
    ///   controller's pool can't cover the cost (programmer error
    ///   to force-yes when broke). Other variants fall through to
    ///   their own per-variant defaults.
    /// * `"optional_pay_no"` — OptionalManaCostChoice drops without
    ///   paying or applying the inner. Other variants fall through.
    /// * `"scry_keep_top"` — ScryChoice routes the examined card back
    ///   to library top. Other variants fall through to their own
    ///   per-variant defaults.
    /// * `"scry_send_bottom"` — ScryChoice routes the examined card to
    ///   library bottom. Other variants fall through.
    /// * `"default"` — Surveil keeps all on top; MayDo + IfYouDo
    ///   answer "yes"; PickCardFromExamined picks the topmost
    ///   examined card; ChooseModeChoice picks `modes[0]`; the
    ///   OptionalManaCostChoice does the Python-parity "pay if
    ///   affordable, else skip" (mirrors the base-Agent default in
    ///   Python); ScryChoice routes the examined card back to library
    ///   top (conservative non-decision).
    ///
    /// Raises `ValueError` on an unknown strategy.
    fn auto_resolve_pending_decisions(&mut self, strategy: &str) -> PyResult<()> {
        auto_resolve_pending(self, strategy)
    }
}
