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

use crate::state::{GameObject, GameState, PendingDecision};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::sync::Arc;

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
        | "default" => {}
        other => {
            return Err(PyValueError::new_err(format!(
                "auto_resolve_pending_decisions: unknown strategy {other:?}; \
                 valid strategies: keep_all_on_top, send_all_to_graveyard, \
                 may_do_yes, may_do_no, pick_top, choose_mode_0, \
                 if_you_do_yes, if_you_do_no, manifest_top, default"
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
                inner_effect,
                ..
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
                    crate::state_ops_resolve::apply_effect_pub(
                        state,
                        &inner_effect,
                        source_obj_id,
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
                modes,
                ..
            } => {
                // "default" / "choose_mode_0" → pick modes[0]. Other
                // strategies fall through to the same default for
                // robustness (matches Python's no-agent-seated
                // fallback in ModalChooseOne.resolve). An empty modes
                // Vec is a programmer error at the parse layer; if
                // it ever reaches here we drop the decision silently
                // rather than panic.
                if !modes.is_empty() {
                    crate::state_ops_resolve::apply_effect_pub(
                        state,
                        &modes[0],
                        source_obj_id,
                    )?;
                }
            }
            PendingDecision::IfYouDoChoice {
                source_obj_id,
                do_action,
                then_action,
                ..
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
                    crate::state_ops_resolve::apply_effect_pub(
                        state,
                        &do_action,
                        source_obj_id,
                    )?;
                    crate::state_ops_resolve::apply_effect_pub(
                        state,
                        &then_action,
                        source_obj_id,
                    )?;
                }
            }
            PendingDecision::ManifestDreadChoice {
                source_obj_id,
                controller,
                cards,
                then_attach_to_source,
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
                resolve_manifest_dread_to_battlefield(
                    state,
                    source_obj_id,
                    controller,
                    cards,
                    /*chosen_idx*/ 0,
                    then_attach_to_source,
                )?;
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
/// Out-of-range `chosen_idx` or an empty cards Vec returns Ok(()) —
/// the empty case is the legitimate library-exhausted no-op path.
/// (When `then_attach_to_source` is true and the cards Vec is empty,
/// no manifested permanent exists so the attach step is naturally
/// skipped.)
fn resolve_manifest_dread_to_battlefield(
    state: &mut GameState,
    source_obj_id: u32,
    controller: u8,
    cards: Vec<GameObject>,
    chosen_idx: usize,
    then_attach_to_source: bool,
) -> PyResult<()> {
    if chosen_idx >= cards.len() {
        // Empty cards Vec (library was empty) → no-op success. No
        // manifested permanent → attach step is naturally a no-op.
        return Ok(());
    }
    let pidx = controller as usize;
    let mut sorted_cards = cards;
    let chosen = sorted_cards.remove(chosen_idx);
    let manifested_id = chosen.id;
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
        bf_mut.push(obj);
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
            // was popped FIRST (it was the topmost card). To restore
            // the original ordering we push them back in REVERSE
            // popped-order so cards[0] ends up on the top (last
            // position of the Vec) again. With cards = [top, second-
            // from-top, third-from-top], pushing in reverse means
            // pushing third, second, top — the final state has top
            // at Vec.last().
            let pidx = controller as usize;
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            for obj in cards.into_iter().rev() {
                lib_mut.push(obj);
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
                } => {
                    d.set_item("kind", "ManifestDreadChoice")?;
                    d.set_item("source_obj_id", *source_obj_id)?;
                    d.set_item("controller", *controller)?;
                    let card_ids: Vec<u32> = cards.iter().map(|o| o.id).collect();
                    d.set_item("cards", card_ids)?;
                    d.set_item("then_attach_to_source", *then_attach_to_source)?;
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
        // depth: card_ids_to_top[0] is the topmost (Vec.last()),
        // card_ids_to_top[1] is second-from-top, etc. So push in
        // REVERSE submitted order: the last id pushed lands on
        // top (Vec.last()), and that's index 0 of the submitted
        // list.
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
                lib_mut.push(obj);
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
        let (source_obj_id, inner_effect) = match decision {
            PendingDecision::MayDoChoice {
                source_obj_id,
                inner_effect,
                ..
            } => (source_obj_id, inner_effect),
            // Unreachable: we just validated head was MayDoChoice
            // above. The pattern is here for the irrefutable-match
            // shape only.
            _ => unreachable!("validated above"),
        };
        if yes {
            crate::state_ops_resolve::apply_effect_pub(
                self,
                &inner_effect,
                source_obj_id,
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
        let (source_obj_id, modes) = match decision {
            PendingDecision::ChooseModeChoice {
                source_obj_id, modes, ..
            } => (source_obj_id, modes),
            _ => unreachable!("validated above"),
        };
        crate::state_ops_resolve::apply_effect_pub(
            self,
            &modes[chosen_idx],
            source_obj_id,
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
        let (source_obj_id, do_action, then_action) = match decision {
            PendingDecision::IfYouDoChoice {
                source_obj_id,
                do_action,
                then_action,
                ..
            } => (source_obj_id, do_action, then_action),
            _ => unreachable!("validated above"),
        };
        if yes {
            crate::state_ops_resolve::apply_effect_pub(
                self,
                &do_action,
                source_obj_id,
            )?;
            crate::state_ops_resolve::apply_effect_pub(
                self,
                &then_action,
                source_obj_id,
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
        let (source_obj_id, controller, cards, then_attach_to_source) = match decision {
            PendingDecision::ManifestDreadChoice {
                source_obj_id,
                controller,
                cards,
                then_attach_to_source,
            } => (source_obj_id, controller, cards, then_attach_to_source),
            _ => unreachable!("validated above"),
        };
        resolve_manifest_dread_to_battlefield(
            self,
            source_obj_id,
            controller,
            cards,
            chosen_idx,
            then_attach_to_source,
        )
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
    /// * `"default"` — Surveil keeps all on top; MayDo + IfYouDo
    ///   answer "yes"; PickCardFromExamined picks the topmost
    ///   examined card; ChooseModeChoice picks `modes[0]` (mirrors
    ///   the base-Agent default in Python).
    ///
    /// Raises `ValueError` on an unknown strategy.
    fn auto_resolve_pending_decisions(&mut self, strategy: &str) -> PyResult<()> {
        auto_resolve_pending(self, strategy)
    }
}
