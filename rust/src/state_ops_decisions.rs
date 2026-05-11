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
        "keep_all_on_top" | "send_all_to_graveyard" => {}
        other => {
            return Err(PyValueError::new_err(format!(
                "auto_resolve_pending_decisions: unknown strategy {other:?}; \
                 valid strategies: keep_all_on_top, send_all_to_graveyard"
            )))
        }
    }
    while !state.pending_decisions.is_empty() {
        let decision = state.pending_decisions.remove(0);
        match decision {
            PendingDecision::SurveilChoice {
                controller, cards, ..
            } => {
                resolve_surveil_with_strategy(state, controller, cards, strategy)?;
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

    /// Drain the pending-decisions queue using a deterministic
    /// strategy. Useful for callers that don't model the choice
    /// dimension (training harnesses, parity tests, deterministic
    /// regression scenarios).
    ///
    /// Strategies:
    /// * `"keep_all_on_top"` — Surveil returns every observed card
    ///   to the library top, preserving the order they were popped
    ///   (the r23 deterministic baseline behavior, bit-equal to the
    ///   pre-r27 path).
    /// * `"send_all_to_graveyard"` — Surveil sends every observed
    ///   card to the controller's graveyard, in popped order.
    ///
    /// Raises `ValueError` on an unknown strategy.
    fn auto_resolve_pending_decisions(&mut self, strategy: &str) -> PyResult<()> {
        auto_resolve_pending(self, strategy)
    }
}
