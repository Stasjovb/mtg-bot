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
    // G7 S6-Class-E ordered-pool: route the per-color decrements
    // through the `coins`-vec-aware helper so the insertion-ordered
    // SoT and per-color count cache stay synced. The drain ORDER is
    // preserved verbatim (legacy C→W→U→B→R→G generic-priority) for
    // parity-neutral migration; this fn is the decision-callback
    // count-only legacy pay primitive, NOT the Class-E
    // `auto_tap_for_cost` SoT path. Class E is fixed at the call
    // site that DOES route through Python's `auto_tap_for_cost` SoT
    // — `auto_tap_pay_for_cost` in `state_ops_cast.rs`.
    pool.drain_first_n_color(b'W', cost.white as u32);
    pool.drain_first_n_color(b'U', cost.blue as u32);
    pool.drain_first_n_color(b'B', cost.black as u32);
    pool.drain_first_n_color(b'R', cost.red as u32);
    pool.drain_first_n_color(b'G', cost.green as u32);
    let mut remaining_generic = cost.generic as u32;
    for color in [b'C', b'W', b'U', b'B', b'R', b'G'] {
        if remaining_generic == 0 {
            break;
        }
        let avail = match color {
            b'W' => pool.white as u32,
            b'U' => pool.blue as u32,
            b'B' => pool.black as u32,
            b'R' => pool.red as u32,
            b'G' => pool.green as u32,
            b'C' => pool.colorless as u32,
            _ => 0,
        };
        let take = avail.min(remaining_generic);
        pool.drain_first_n_color(color, take);
        remaining_generic -= take;
    }
    debug_assert_eq!(remaining_generic, 0);
    pool.assert_count_sync();
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
        | "tap_permanent_decline"
        | "tap_permanent_first"
        | "enchant_target_first"
        | "may_discard_yes"
        | "may_discard_no"
        | "opponent_hand_card_first"
        | "graveyard_card_first"
        | "default" => {}
        other => {
            return Err(PyValueError::new_err(format!(
                "auto_resolve_pending_decisions: unknown strategy {other:?}; \
                 valid strategies: keep_all_on_top, send_all_to_graveyard, \
                 may_do_yes, may_do_no, pick_top, choose_mode_0, \
                 if_you_do_yes, if_you_do_no, manifest_top, reveal_yes, \
                 reveal_no, optional_pay_yes, optional_pay_no, \
                 scry_keep_top, scry_send_bottom, tap_permanent_decline, \
                 tap_permanent_first, enchant_target_first, \
                 may_discard_yes, may_discard_no, \
                 opponent_hand_card_first, graveyard_card_first, default"
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
                    // Round-37 sister-composer ordering fix
                    // (mirrors round-36 Effect::Sequence drain at
                    // state_ops_resolve.rs:5151). If do_action itself
                    // pushes a PendingDecision (e.g. the first-slice
                    // shape IfYouDo(MayDo(X), Y) — MayDo's resolve
                    // arm queues a MayDoChoice and short-circuits),
                    // then_action would otherwise run BEFORE X has
                    // actually applied: the queued MayDoChoice would
                    // sit on the queue while DrawCards / GainLife /
                    // etc. fired, then drain late and observe state
                    // already mutated by then_action. Python's
                    // no-agent IfYouDo.resolve runs do_action.resolve()
                    // synchronously (the no-agent shortcut inside the
                    // child applies X inline), so then_action.resolve()
                    // sees a fully-applied do_action. Drain inside the
                    // arm to restore that ordering. Strategy
                    // "keep_all_on_top" matches the round-36 Sequence
                    // fix — equivalent to "default" for every current
                    // decision variant: Surveil routes to keep_all_on_top
                    // (line 177), MayDo says yes (line 192-195),
                    // ChooseMode picks modes[0] (line 226), nested
                    // IfYouDo applies both (line 257), etc. See
                    // docs/SEARCH_LIMITATIONS.md "Sequence(Surveil,
                    // DrawCards) PendingDecision-vs-inline ordering"
                    // follow-up note.
                    auto_resolve_pending(state, "keep_all_on_top")?;
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
            PendingDecision::TapPermanentChoice {
                source_obj_id,
                controller,
                candidates,
            } => {
                // 20th Rust slice (VVV Pin 2 closure) — Command Bridge
                // ETB cost-decision auto-resolve.
                //
                // "default" / "tap_permanent_decline" / unrelated
                //   -> decline -> sacrifice source. Matches Python's
                //   no-agent-seated fallback at combinators.py:139-141
                //   (`chosen = None` when `p.agent is None` -> the
                //   decline branch sacrifices the source).
                //
                // "tap_permanent_first" -> tap candidates[0] (the
                //   FIRST-listed untapped permanent). Mirrors the
                //   `pick_top` / `choose_mode_0` deterministic-first
                //   strategy precedent for cases where a test fixture
                //   wants to exercise the keep-source branch under
                //   auto-resolve (no agent seated).
                let tap_first =
                    matches!(strategy, "tap_permanent_first");
                if tap_first && !candidates.is_empty() {
                    apply_tap_permanent_keep_source(
                        state,
                        controller,
                        candidates[0],
                    )?;
                } else {
                    // Decline -> sacrifice the source via the same
                    // helper the Effect arm uses for the empty-
                    // candidates path. Mirrors Python parity
                    // (combinators.py:142-148).
                    crate::state_ops_resolve::sacrifice_source_for_tap_decline(
                        state,
                        controller as usize,
                        source_obj_id,
                    )?;
                }
            }
            PendingDecision::EnchantTargetChoice {
                source_obj_id,
                controller: _,
                candidates,
            } => {
                // **Aura-attachment substrate — Phase 1 STEP 3
                // (round-78, 2026-05-20) — auto-resolve.**
                //
                // "default" / "enchant_target_first" / unrelated
                //   -> bind candidates[0] onto the matching StackItem's
                //   `target_obj_id`. The cast arm only pushes this
                //   decision when the candidate set is non-empty, so
                //   `candidates[0]` is always a valid id. Mirrors the
                //   `_PickFirstLegalTargetAgent` bench/probe convention
                //   every other cast-time target picker uses (Radiant
                //   Strike, Focus Fire, Seedship Impact — see
                //   `state_ops_cast.rs:1614-1714`).
                //
                // **Locating the StackItem.** Walk the stack from the
                // top (LIFO) to find the spell StackItem whose
                // `source_obj_id` matches the decision's source. The
                // decision was pushed by `cast_aura` AFTER the
                // StackItem push, so the StackItem MUST exist on the
                // stack at this point (no zone-change can have
                // happened — the stack stays put during the
                // priority round).
                if !candidates.is_empty() {
                    bind_enchant_target_to_stack_item(
                        state,
                        source_obj_id,
                        candidates[0],
                    );
                }
                // Empty-candidates case is structurally impossible (cast
                // arm skips the push), but defensively a no-op leaves
                // target_obj_id=None so STEP 4 fizzles on resolve —
                // matches the "no legal target chosen" semantics.
            }
            PendingDecision::GraveyardCardChoice {
                source_obj_id: _,
                controller: _,
                candidates,
            } => {
                // **Aura Phase 3+ Phase A Cycle 1 (2026-05-25) — Chorale
                // of the Void substrate landing — auto-resolve.**
                //
                // "default" / "graveyard_card_first" / unrelated -> pick
                // candidates[0] (the deterministic-first legal target in
                // the build order — player-id then graveyard position).
                // The push arm only enqueues this decision when the
                // candidate set is non-empty (every Phase-3+ admit path
                // gates push on a non-empty target enumeration); the
                // empty-candidates case is therefore an absorbing no-op.
                // Mirrors `EnchantTargetChoice`'s default contract.
                //
                // **Where the chosen id lands.** Writing into
                // `current_resolve_payload_target_id` (the engine-wide
                // resolver-bound target slot per
                // `state_ops_resolve.rs:5639+`). The resolve arm for
                // `Effect::ReanimateTargetCreatureCardFromDefendersGraveyard`
                // reads that slot at the head of its execution.
                if !candidates.is_empty() {
                    state.current_resolve_payload_target_id =
                        Some(candidates[0]);
                }
            }
            PendingDecision::MayDiscardChoice {
                source_obj_id,
                controller,
                target_player_id,
                nonland_card_ids,
            } => {
                // **Aura Phase 3+ Phase B Cycle 1 (2026-05-26) — Cracked
                // Skull substrate landing — auto-resolve.**
                //
                // "default" / "may_discard_yes" / unrelated -> say YES
                // (matches Python's default Agent's choose_yes_no
                // returning True, mirrors the MayDoChoice default-yes
                // convention).
                //
                // On YES we must enqueue the SECOND PendingDecision —
                // OpponentHandCardChoice — carrying the same source +
                // controller + target_player_id + the nonland_card_ids
                // snapshot. The production push path will hit this same
                // arm when the trigger-fire push reaches the decision
                // queue.
                //
                // On NO (strategy = "may_discard_no") we drop the
                // decision without enqueueing the follow-up — Python
                // parity with the "caster declines the may-discard"
                // log + return path at `discard.py:368-372`.
                let say_yes = !matches!(strategy, "may_discard_no");
                if say_yes {
                    state.pending_decisions.insert(
                        0,
                        PendingDecision::OpponentHandCardChoice {
                            source_obj_id,
                            controller,
                            target_player_id,
                            candidates: nonland_card_ids,
                        },
                    );
                }
            }
            PendingDecision::OpponentHandCardChoice {
                source_obj_id: _,
                controller: _,
                target_player_id,
                candidates,
            } => {
                // **Aura Phase 3+ Phase B Cycle 1 (2026-05-26) — Cracked
                // Skull substrate landing — auto-resolve.**
                //
                // "default" / "opponent_hand_card_first" / unrelated ->
                // pick candidates[0] (the deterministic-first legal
                // target — mirrors the GraveyardCardChoice /
                // EnchantTargetChoice convention).
                //
                // The chosen card is then moved from the target's hand
                // to their graveyard with CR 400.7 zone-change reset.
                // The push arm only enqueues this decision when the
                // candidate set is non-empty (the may-gate's nonland-
                // options gate already gated push on non-empty); empty-
                // candidates is therefore an absorbing no-op (defensive).
                if !candidates.is_empty() {
                    let chosen_id = candidates[0];
                    let tgt_idx = target_player_id as usize;
                    if tgt_idx < state.players.len() {
                        apply_opponent_hand_discard(
                            state, tgt_idx, chosen_id,
                        );
                    }
                }
            }
        }
    }
    Ok(())
}

/// **Aura Phase 3+ Phase B Cycle 1 (2026-05-26) — Cracked Skull
/// substrate landing — opponent-hand discard helper.** Move
/// `chosen_id` from `state.players[target_idx].hand` to
/// `state.players[target_idx].graveyard` with CR 400.7 zone-change
/// reset stamping. Mirrors Python's
/// `target.hand.remove(chosen); chosen.zone = Zone.GRAVEYARD;
/// target.graveyard.append(chosen)` at `discard.py:379-381`. Silent
/// no-op if `chosen_id` is no longer in the hand (defensive — covers
/// the race-with-mid-flight-hand-change case Python doesn't model).
fn apply_opponent_hand_discard(
    state: &mut crate::state::GameState,
    target_idx: usize,
    chosen_id: u32,
) {
    let hand_mut: &mut Vec<crate::state::GameObject> = std::sync::Arc::make_mut(
        &mut state.players[target_idx].hand,
    );
    let Some(pos) = hand_mut.iter().position(|o| o.id == chosen_id) else {
        return;
    };
    let mut obj = hand_mut.remove(pos);
    // CR 400.7 zone-change reset.
    obj.zone = crate::state_ops_zones::ZONE_GRAVEYARD;
    obj.tapped = false;
    obj.summoning_sick = false;
    obj.damage = 0;
    obj.counters = 0;
    obj.attached_to = None;
    obj.exiled_with_source = None;
    obj.publicly_known_to_caster_bits = 0;
    std::sync::Arc::make_mut(&mut state.players[target_idx].graveyard)
        .push(obj);
}

/// **Aura-attachment substrate — Phase 1 STEP 3 (round-78).** Locate
/// the spell StackItem whose `source_obj_id` matches `aura_source_id`
/// and stamp `target_obj_id = Some(host_id)`. Used by
/// `submit_enchant_target_decision` (manual submit path) and the
/// auto-resolve arm (deterministic-first default).
///
/// **Walks the stack top-down (LIFO).** The decision was queued by
/// `cast_aura` AFTER pushing the StackItem, so the StackItem is at
/// or near the top — the loop is bounded by the stack depth, in
/// practice tiny. If multiple Aura StackItems happened to share a
/// source_obj_id (cannot happen — `obj_id` is unique per
/// `GameObject`), the topmost match wins.
///
/// **Silent partial on missing StackItem.** If no StackItem matches
/// (the spell already resolved between cast and submit — e.g. an
/// instant-speed effect drained the stack? — defensive, should not
/// happen given the push-then-decision ordering), this is a silent
/// no-op. The Aura on bf rides with `attached_to = None` and STEP
/// 4's resolve arm fizzles per CR 608.2b illegal-target shape. Same
/// defensive contract `apply_tap_permanent_keep_source` uses for the
/// LTB-during-decision-window edge case.
fn bind_enchant_target_to_stack_item(
    state: &mut crate::state::GameState,
    aura_source_id: u32,
    host_id: u32,
) {
    for item in state.stack.iter_mut().rev() {
        if item.source_obj_id == aura_source_id
            && matches!(item.kind, crate::state::StackItemKind::Spell)
        {
            item.target_obj_id = Some(host_id);
            return;
        }
    }
    // No matching StackItem — silent no-op (defensive; the
    // cast-push-then-decision-push ordering should keep the
    // StackItem reachable until the decision is resolved).
}

/// **20th Rust slice (VVV Pin 2 closure) — tap-keep-source helper.**
/// Apply the "tap the chosen permanent; keep the source" branch of
/// the `PendingDecision::TapPermanentChoice` resolve. Mirrors Python's
/// `tap_permanent(state, target)` call at `combinators.py:163`.
///
/// **Idempotent on already-tapped permanents.** A submit racing with
/// another effect that tapped the candidate in the meantime is a
/// silent no-op on the tap (the source still keeps surviving — the
/// decision contract is "you chose to tap THAT permanent"; the
/// tap-already-applied case satisfies the contract). Mirrors
/// `Effect::TapTarget`'s idempotent shape.
///
/// Defensive: if `chosen_id` is no longer on `controller`'s bf
/// (LTB'd between push and submit), the tap is a silent partial. The
/// submit dispatcher's validation already runs the bf-presence check
/// at submit time before reaching this helper.
fn apply_tap_permanent_keep_source(
    state: &mut GameState,
    controller: u8,
    chosen_id: u32,
) -> PyResult<()> {
    let cidx = controller as usize;
    let bf_mut = std::sync::Arc::make_mut(
        &mut state.players[cidx].battlefield,
    );
    for obj in bf_mut.iter_mut() {
        if obj.id == chosen_id {
            obj.tapped = true;
            // BECOMES_TAPPED event dispatch is the standard tap-event
            // sibling to `Effect::TapTarget`'s dispatch — mirrors the
            // existing TapTarget arm's "fire BECOMES_TAPPED only if
            // the object was untapped pre-tap". Inline rather than
            // re-locating via the TapTarget primitive (E0624 cross-
            // file friction the other inline tap call sites already
            // accept — Sacrifice / AddCounters / TapTarget all inline
            // their primitives).
            break;
        }
    }
    crate::state_ops_resolve::dispatch_event(
        state,
        crate::cards::Event::BecomesTapped,
        chosen_id,
    )?;
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
/// - `"spacecraft"`: any Spacecraft card. Spacecraft is an artifact
///   SUBTYPE (the printed type line is `Artifact — Spacecraft`:
///   `card_types == ("Artifact",)`, `subtypes == ("Spacecraft",)`),
///   NOT a top-level card type — verified against
///   `data/edge_of_eternities.json` (Lumen-Class Frigate, Rescue
///   Skiff, Wedgelight Rammer, The Seriema, …). So this reads
///   `printing.subtypes`, mirroring Python's source of truth
///   (`LookAtTopNRevealOrCounter._matches` → `printing.is_spacecraft`
///   → `"Spacecraft" in printing.subtypes`) and the campaign's own
///   `or_spacecraft` filter family (`cards.rs:2014-2027`). The prior
///   first-slice `card_types` check ("Rust printings don't yet track
///   subtypes") was stale — `CardPrinting.subtypes` has long existed
///   on the Rust side — and never matched a real EoE Spacecraft;
///   round-55 N3's genuine real-EoE Pulsar Squadron Ace probe found
///   the resulting reveal-path divergence (round-56 Rust-lane fix,
///   SEARCH_LIMITATIONS.md).
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
            // Spacecraft is an artifact SUBTYPE, not a card type:
            // real EoE Spacecraft are `Artifact — Spacecraft`
            // (card_types=["Artifact"], subtypes=["Spacecraft"]).
            // Mirror Python's `is_spacecraft` (`"Spacecraft" in
            // subtypes`) and the existing `or_spacecraft` family
            // (cards.rs:2014-2027). The prior `card_types` check
            // never matched a real Spacecraft (round-55 N3 find).
            printing.subtypes.iter().any(|s| s == "Spacecraft")
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
                PendingDecision::TapPermanentChoice {
                    source_obj_id,
                    controller,
                    candidates,
                } => {
                    // 20th Rust slice (VVV Pin 2 closure) — Command
                    // Bridge cost-decision surface dict. `candidates`
                    // is the flat list of untapped-permanent ids the
                    // controller may tap (source-excluded at push
                    // time). Same idiom as SurveilChoice's flat
                    // `cards: Vec<u32>` (id-based dispatch rather
                    // than full GameObject payload — candidates live
                    // on the battlefield, so re-locating by id at
                    // submit time is the natural pattern).
                    d.set_item("kind", "TapPermanentChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    d.set_item("candidates", candidates.clone())?;
                }
                PendingDecision::EnchantTargetChoice {
                    source_obj_id,
                    controller,
                    candidates,
                } => {
                    // **Aura-attachment substrate — Phase 1 STEP 3
                    // (round-78).** Cast-time enchant-target choice
                    // surface dict. `candidates` is the flat list of
                    // legal enchant targets per the printing's
                    // `aura_enchant_type` + `aura_yours_only` filter
                    // (computed at `cast_aura` push time, ordered by
                    // `bf_iter_etb_sorted`). Same id-based idiom as
                    // `TapPermanentChoice`. The controller drains via
                    // `submit_enchant_target_decision(Some(id))` —
                    // the id binds onto the matching spell
                    // StackItem's `target_obj_id` so STEP 4 can read
                    // it at resolve time.
                    d.set_item("kind", "EnchantTargetChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    d.set_item("candidates", candidates.clone())?;
                }
                PendingDecision::GraveyardCardChoice {
                    source_obj_id,
                    controller,
                    candidates,
                } => {
                    // **Aura Phase 3+ Phase A Cycle 1 (2026-05-25) —
                    // Chorale of the Void substrate landing — pending-
                    // decisions surface dict.** `candidates` is the
                    // flat list of graveyard-creature ids enumerated
                    // across all non-controller players' graveyards
                    // (player-id then position order). Same id-based
                    // idiom as `TapPermanentChoice` /
                    // `EnchantTargetChoice`. The controller drains via
                    // `submit_graveyard_card_decision(Some(id))` —
                    // the id binds onto `current_resolve_payload_
                    // target_id` so the
                    // `ReanimateTargetCreatureCardFromDefendersGraveyard`
                    // resolve arm can read it.
                    d.set_item("kind", "GraveyardCardChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    d.set_item("candidates", candidates.clone())?;
                }
                PendingDecision::MayDiscardChoice {
                    source_obj_id,
                    controller,
                    target_player_id,
                    nonland_card_ids,
                } => {
                    // **Aura Phase 3+ Phase B Cycle 1 (2026-05-26) —
                    // Cracked Skull substrate landing — pending-
                    // decisions surface dict.** `nonland_card_ids` is
                    // the snapshot of the target opponent's hand
                    // filtered to non-land cards (the options for the
                    // directed discard the controller is being asked
                    // about). The controller drains via
                    // `submit_may_discard_decision(yes_no)` — `True`
                    // enqueues the follow-up `OpponentHandCardChoice`
                    // carrying the same payload; `False` is a silent
                    // fizzle.
                    d.set_item("kind", "MayDiscardChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    d.set_item("target_player_id", *target_player_id)?;
                    d.set_item("nonland_card_ids", nonland_card_ids.clone())?;
                }
                PendingDecision::OpponentHandCardChoice {
                    source_obj_id,
                    controller,
                    target_player_id,
                    candidates,
                } => {
                    // **Aura Phase 3+ Phase B Cycle 1 (2026-05-26) —
                    // Cracked Skull substrate landing — pending-
                    // decisions surface dict.** `candidates` is the
                    // flat list of nonland card ids in the target
                    // opponent's hand. The controller drains via
                    // `submit_opponent_hand_card_decision(Some(id))` —
                    // the id is removed from the target's hand and
                    // moved to their graveyard with CR 400.7 zone-
                    // change reset.
                    d.set_item("kind", "OpponentHandCardChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    d.set_item("target_player_id", *target_player_id)?;
                    d.set_item("candidates", candidates.clone())?;
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

    /// **20th Rust slice (VVV Pin 2 closure) — submit a tap-permanent
    /// cost-decision.** Consumes the head `TapPermanentChoice` on the
    /// pending-decisions queue.
    ///
    /// On `chosen_id = Some(id)`, tap the chosen permanent and keep
    /// the source on the battlefield (Python: `tap_permanent(state,
    /// target)` at `combinators.py:163`). `id` MUST be one of the
    /// candidate ids; an unknown id raises `ValueError`
    /// transactionally (no mutation on failure).
    ///
    /// On `chosen_id = None`, decline -> sacrifice the source (Python:
    /// `_sacrifice(state, source)` at `combinators.py:147` —
    /// no-agent-seated fallback or explicit decline).
    ///
    /// Powers Command Bridge's ETB "sacrifice this unless you tap an
    /// untapped permanent you control" (`Effect::SacrificeSelfUnlessTap
    /// Permanent`). The controller's agent normally drives the choice
    /// via this submit; the auto-resolve drain (`"default"` /
    /// `"tap_permanent_decline"`) declines + sacrifices, and the
    /// alternative `"tap_permanent_first"` deterministically picks
    /// `candidates[0]` (test-fixture path).
    ///
    /// Raises `ValueError` if:
    /// - the queue is empty
    /// - the head is not a `TapPermanentChoice`
    /// - `chosen_id = Some(id)` and `id` is not in the candidate set
    #[pyo3(signature = (chosen_id=None))]
    fn submit_tap_permanent_decision(
        &mut self,
        chosen_id: Option<u32>,
    ) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_tap_permanent_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation on a discriminant
        // mismatch or unknown chosen_id.
        match &self.pending_decisions[0] {
            PendingDecision::TapPermanentChoice { candidates, .. } => {
                if let Some(id) = chosen_id {
                    if !candidates.contains(&id) {
                        return Err(PyValueError::new_err(format!(
                            "submit_tap_permanent_decision: chosen_id \
                             {id} is not one of the candidate \
                             untapped-permanent ids {:?}",
                            candidates
                        )));
                    }
                }
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_tap_permanent_decision: head of pending-\
                     decisions queue is not a TapPermanentChoice (got \
                     {:?}); call the variant-specific submit_* \
                     dispatcher (e.g. submit_surveil_decision)",
                    std::mem::discriminant(other)
                )));
            }
        }
        // Validation passed — consume the head and route.
        let decision = self.pending_decisions.remove(0);
        let (source_obj_id, controller) = match decision {
            PendingDecision::TapPermanentChoice {
                source_obj_id,
                controller,
                ..
            } => (source_obj_id, controller),
            _ => unreachable!("validated above"),
        };
        match chosen_id {
            Some(id) => apply_tap_permanent_keep_source(self, controller, id),
            None => crate::state_ops_resolve::sacrifice_source_for_tap_decline(
                self,
                controller as usize,
                source_obj_id,
            ),
        }
    }

    /// **Aura-attachment substrate — Phase 1 STEP 3 (round-78,
    /// 2026-05-20).** Consume the head `EnchantTargetChoice` on the
    /// pending-decisions queue: bind `chosen_id` (Some -> the legal
    /// host the caster picked; None -> no target chosen, the Aura
    /// fizzles on resolve per CR 608.2b / Python parity at
    /// `actions.py:2740-2745`) onto the matching spell StackItem's
    /// `target_obj_id` so STEP 4's resolve arm can read it.
    ///
    /// Mirrors Python's cast-time agent pick at
    /// `actions.py:1337-1357`: the caster's `agent.choose_target`
    /// either returns one of the legal `(kind, id)` tuples (Some) or
    /// `None` (chose no target — the cast still completes but
    /// resolves to nothing).
    ///
    /// **Submit contract.** `chosen_id` MUST be one of the candidate
    /// ids in the head's `candidates` Vec OR `None`. An unknown id
    /// raises `ValueError` transactionally — no mutation on failure,
    /// the decision stays at the head of the queue.
    ///
    /// **StackItem mutation.** On `Some(id)`, the matching StackItem
    /// (located by `source_obj_id`) has its `target_obj_id` set to
    /// `Some(id)`. On `None`, the StackItem's `target_obj_id` stays
    /// `None` (the cast already pushed with `None` defaults). Either
    /// way the decision is consumed from the queue.
    ///
    /// Raises `ValueError` if:
    /// - the queue is empty
    /// - the head is not an `EnchantTargetChoice`
    /// - `chosen_id = Some(id)` and `id` is not in the candidate set
    #[pyo3(signature = (chosen_id=None))]
    fn submit_enchant_target_decision(
        &mut self,
        chosen_id: Option<u32>,
    ) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_enchant_target_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation on a discriminant
        // mismatch or unknown chosen_id.
        match &self.pending_decisions[0] {
            PendingDecision::EnchantTargetChoice { candidates, .. } => {
                if let Some(id) = chosen_id {
                    if !candidates.contains(&id) {
                        return Err(PyValueError::new_err(format!(
                            "submit_enchant_target_decision: chosen_id \
                             {id} is not one of the candidate \
                             enchant-target ids {:?}",
                            candidates
                        )));
                    }
                }
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_enchant_target_decision: head of pending-\
                     decisions queue is not an EnchantTargetChoice (got \
                     {:?}); call the variant-specific submit_* \
                     dispatcher (e.g. submit_surveil_decision)",
                    std::mem::discriminant(other)
                )));
            }
        }
        // Validation passed — consume the head and route.
        let decision = self.pending_decisions.remove(0);
        let source_obj_id = match decision {
            PendingDecision::EnchantTargetChoice { source_obj_id, .. } => {
                source_obj_id
            }
            _ => unreachable!("validated above"),
        };
        if let Some(id) = chosen_id {
            bind_enchant_target_to_stack_item(self, source_obj_id, id);
        }
        // `None` -> no-op on the StackItem: target_obj_id stays None
        // (the cast pushed with None defaults). STEP 4 will fizzle on
        // resolve per Python parity.
        Ok(())
    }

    /// **Aura Phase 3+ Phase A Cycle 1 (2026-05-25) — Chorale of the
    /// Void substrate landing.** Consume the head `GraveyardCardChoice`
    /// on the pending-decisions queue: bind `chosen_id` (Some -> the
    /// legal graveyard creature the controller picked; None -> no
    /// target chosen, the resolve arm fizzles silently) into
    /// `current_resolve_payload_target_id` so the
    /// `Effect::ReanimateTargetCreatureCardFromDefendersGraveyard`
    /// resolve arm reads it.
    ///
    /// **Submit contract.** `chosen_id` MUST be one of the candidate
    /// ids in the head's `candidates` Vec OR `None`. An unknown id
    /// raises `ValueError` transactionally — no mutation on failure,
    /// the decision stays at the head of the queue.
    ///
    /// **Where the chosen id lands.** Writing into
    /// `current_resolve_payload_target_id` (the engine-wide resolver-
    /// bound target slot used by every "cast-time / trigger-time bound
    /// single target" resolve arm —
    /// `ReturnTargetArtifactCardFromYourGraveyardToHand` at
    /// `state_ops_resolve.rs:5639+` is the closest precedent). The
    /// `Effect::ReanimateTargetCreatureCardFromDefendersGraveyard`
    /// resolve arm reads that slot at the head of its execution + re-
    /// validates (still in opponent's graveyard, still a creature
    /// card) per CR 608.2b.
    ///
    /// Raises `ValueError` if:
    /// - the queue is empty
    /// - the head is not a `GraveyardCardChoice`
    /// - `chosen_id = Some(id)` and `id` is not in the candidate set
    ///
    /// **Substrate-only landing (Cycle 1) — invariant.** No production
    /// admit path pushes this decision today (the
    /// `_aura_triggers_are_phase3_safe` gate ships in Cycle 2). The
    /// submit dispatcher is in place so Cycle 1's substrate pins can
    /// exercise the push + drain + payload-bind shape directly. Cycle
    /// 2 wires the admit predicate AND the trigger-fire push site
    /// together — chorale of the Void flips DECLINED → ADMITTED then.
    #[pyo3(signature = (chosen_id=None))]
    fn submit_graveyard_card_decision(
        &mut self,
        chosen_id: Option<u32>,
    ) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_graveyard_card_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation on a discriminant
        // mismatch or unknown chosen_id.
        match &self.pending_decisions[0] {
            PendingDecision::GraveyardCardChoice { candidates, .. } => {
                if let Some(id) = chosen_id {
                    if !candidates.contains(&id) {
                        return Err(PyValueError::new_err(format!(
                            "submit_graveyard_card_decision: chosen_id \
                             {id} is not one of the candidate \
                             graveyard-creature ids {:?}",
                            candidates
                        )));
                    }
                }
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_graveyard_card_decision: head of pending-\
                     decisions queue is not a GraveyardCardChoice (got \
                     {:?}); call the variant-specific submit_* \
                     dispatcher (e.g. submit_surveil_decision)",
                    std::mem::discriminant(other)
                )));
            }
        }
        // Validation passed — consume the head and route.
        let _decision = self.pending_decisions.remove(0);
        // `Some` -> write into the payload slot the resolve arm reads.
        // `None` -> explicit "no target chosen" path -> CLEAR the slot
        // so the resolve arm's payload-bound branch sees None AND ALSO
        // skips the deterministic-first fallback (the chosen-None
        // semantics is "the controller declined to pick" — distinct
        // from "no production binder ran"; the resolve arm distinguishes
        // these via the dedicated `Option<u32>` slot via a sentinel
        // check at its head). For Cycle-1 substrate the simplest
        // contract is: setting `None` produces a silent fizzle on the
        // next resolve, mirroring Python's "if not targets: return"
        // from `graveyard.py:527-528`. Tests gate on this contract
        // directly.
        self.current_resolve_payload_target_id = chosen_id;
        Ok(())
    }

    /// **Aura Phase 3+ Phase B Cycle 1 (2026-05-26) — Cracked Skull
    /// substrate landing — may-discard yes/no submit.** Consume the
    /// head `MayDiscardChoice` on the pending-decisions queue.
    ///
    /// On `yes = true`, pushes a follow-up
    /// `PendingDecision::OpponentHandCardChoice` at the FRONT of the
    /// queue carrying the same source / controller / target_player_id
    /// + the `nonland_card_ids` snapshot taken at may-gate push time.
    /// On `yes = false`, simply consumes the head — silent fizzle,
    /// matching Python's `state.log.append(...); return` at
    /// `discard.py:368-372`.
    ///
    /// Raises `ValueError` if:
    /// - the queue is empty
    /// - the head is not a `MayDiscardChoice`
    ///
    /// **Substrate-only landing (Cycle 1).** Same scope notes as
    /// `submit_graveyard_card_decision` — no production push site
    /// today; synthetic tests drive the push + drain + payload shape.
    fn submit_may_discard_decision(&mut self, yes: bool) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_may_discard_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation on a discriminant
        // mismatch.
        match &self.pending_decisions[0] {
            PendingDecision::MayDiscardChoice { .. } => {}
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_may_discard_decision: head of pending-\
                     decisions queue is not a MayDiscardChoice (got \
                     {:?}); call the variant-specific submit_* \
                     dispatcher (e.g. submit_surveil_decision)",
                    std::mem::discriminant(other)
                )));
            }
        }
        // Validation passed — consume the head and route.
        let decision = self.pending_decisions.remove(0);
        let PendingDecision::MayDiscardChoice {
            source_obj_id,
            controller,
            target_player_id,
            nonland_card_ids,
        } = decision
        else {
            // Unreachable: the head was just matched as MayDiscardChoice.
            return Ok(());
        };
        if yes {
            // Push the OpponentHandCardChoice at the FRONT of the
            // queue so the next drain step reaches it before any
            // sibling decisions Python's resolve loop would interleave.
            // Mirrors Python's two-call flow at `discard.py:364-378`:
            // the may-gate immediately consults the discard-pick on
            // "yes".
            self.pending_decisions.insert(
                0,
                PendingDecision::OpponentHandCardChoice {
                    source_obj_id,
                    controller,
                    target_player_id,
                    candidates: nonland_card_ids,
                },
            );
        }
        // On `no`, the decision is dropped — Python parity with
        // `state.log.append(...); return` at `discard.py:368-372`.
        Ok(())
    }

    /// **Aura Phase 3+ Phase B Cycle 1 (2026-05-26) — Cracked Skull
    /// substrate landing — opponent-hand-card-discard submit.**
    /// Consume the head `OpponentHandCardChoice` on the pending-
    /// decisions queue.
    ///
    /// On `Some(chosen_id)`, validates `chosen_id` is in the
    /// `candidates` list, then removes the card from the target
    /// opponent's hand and moves it to the target's graveyard with
    /// CR 400.7 zone-change reset stamping. Mirrors Python's
    /// `target.hand.remove(chosen); chosen.zone = Zone.GRAVEYARD;
    /// target.graveyard.append(chosen)` at `discard.py:379-381`.
    /// On `None`, simply consumes the head — silent fizzle (defensive
    /// — the production push path won't hit this because the may-gate
    /// gates entry on non-empty `nonland_card_ids`).
    ///
    /// Raises `ValueError` if:
    /// - the queue is empty
    /// - the head is not an `OpponentHandCardChoice`
    /// - `chosen_id = Some(id)` and `id` is not in the candidate set
    ///
    /// **Substrate-only landing (Cycle 1).** Same scope notes as
    /// `submit_may_discard_decision`.
    #[pyo3(signature = (chosen_id=None))]
    fn submit_opponent_hand_card_decision(
        &mut self,
        chosen_id: Option<u32>,
    ) -> PyResult<()> {
        if self.pending_decisions.is_empty() {
            return Err(PyValueError::new_err(
                "submit_opponent_hand_card_decision: no pending decision",
            ));
        }
        // Inspect head — fail before any mutation on a discriminant
        // mismatch or unknown chosen_id.
        match &self.pending_decisions[0] {
            PendingDecision::OpponentHandCardChoice { candidates, .. } => {
                if let Some(id) = chosen_id {
                    if !candidates.contains(&id) {
                        return Err(PyValueError::new_err(format!(
                            "submit_opponent_hand_card_decision: \
                             chosen_id {id} is not one of the candidate \
                             nonland-card ids {:?}",
                            candidates
                        )));
                    }
                }
            }
            other => {
                return Err(PyValueError::new_err(format!(
                    "submit_opponent_hand_card_decision: head of \
                     pending-decisions queue is not an \
                     OpponentHandCardChoice (got {:?}); call the \
                     variant-specific submit_* dispatcher (e.g. \
                     submit_surveil_decision)",
                    std::mem::discriminant(other)
                )));
            }
        }
        // Validation passed — consume the head and route.
        let decision = self.pending_decisions.remove(0);
        let PendingDecision::OpponentHandCardChoice {
            source_obj_id: _,
            controller: _,
            target_player_id,
            candidates: _,
        } = decision
        else {
            // Unreachable: the head was just matched.
            return Ok(());
        };
        if let Some(id) = chosen_id {
            let tgt_idx = target_player_id as usize;
            if tgt_idx < self.players.len() {
                apply_opponent_hand_discard(self, tgt_idx, id);
            }
        }
        // None -> silent fizzle (defensive; production won't push this
        // path with no candidates).
        Ok(())
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
