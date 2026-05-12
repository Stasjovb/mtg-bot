//! Centralized "battlefield in ETB-timestamp order" iterator.
//!
//! This module owns the shared walk of all battlefield objects across
//! BOTH players, ordered by ETB timestamp (matching Python's
//! `state.battlefield` append-order). The helper is the post-CE4
//! abstraction step: rather than every consumer re-inlining a
//! collect-and-sort, every battlefield-walking reader in the engine
//! that needs ETB-ordered cross-player semantics calls
//! `bf_iter_etb_sorted`.
//!
//! ## Consumers
//!
//! - `state_ops_sba.rs::collect_sba_victims` — CE5 closure (this slice).
//! - `state_ops_combat.rs` damage assignment — CE6 (future).
//! - `state_ops_resolve.rs` cross-player find-first arms — CE7 (future).
//! - Future trigger emitter — gated on CE8 substrate work.
//! - `state_ops_snapshot.rs::battlefield_snapshot` and
//!   `state_ops_fingerprint.rs::fingerprint` currently inline the
//!   collect-and-sort (CE4-closed); they can be refactored to call
//!   this helper as a follow-up post-CE5.
//!
//! ## Tie-break invariant
//!
//! Stable sort: ties (same `etb_timestamp` — possible only when a
//! state's bf was pre-populated without going through a
//! `reserve_etb_timestamp` call, e.g. synthetic-state fixtures where
//! every bf object has timestamp 0) preserve the p0-then-p1,
//! insertion-order walk so pre-CE4 pinned baselines stay bit-equal.
//! This matches the precedent established by
//! `state_ops_snapshot.rs::battlefield_snapshot` (line 189) and
//! `state_ops_fingerprint.rs::fingerprint` (line 316-327) under CE4.
//!
//! ## Borrowing
//!
//! Returns a `Vec<&GameObject>` (NOT an `impl Iterator`) because the
//! underlying p0 + p1 `Arc<Vec<GameObject>>` zones live in separate
//! places on `GameState` and sorting requires a materialized
//! container. The cost is one Vec allocation per call (~16-32 elements
//! in realistic states); the audit's 37 iteration sites are all in
//! non-hot paths (SBA pass, Effect resolution, target selection), so
//! the allocation is negligible relative to per-call downstream work.
//!
//! ## Read-only
//!
//! This helper does not expose a mutable form because every mutating
//! consumer (CE5's SBA destroy pass, CE7's tap/untap target) first
//! IDENTIFIES the target via this read-only walk, then EXTRACTS and
//! MUTATES via the existing per-player `Arc::make_mut` primitives.
//! The collect-then-mutate idiom is the CE4 precedent
//! (`state_ops_sba.rs::apply_sbas` already does this).

use crate::state::{GameObject, GameState};

/// Centralized walk of all battlefield objects across both players,
/// ordered by ETB timestamp (matching Python's `state.battlefield`
/// append-order).
///
/// See the module docstring for invariants. Stable-sort: ties break
/// to the p0-then-p1 insertion-order walk so pre-CE4 baselines stay
/// bit-equal under synthetic-state fixtures.
pub(crate) fn bf_iter_etb_sorted(state: &GameState) -> Vec<&GameObject> {
    let mut refs: Vec<&GameObject> = Vec::with_capacity(
        state.players[0].battlefield.len() + state.players[1].battlefield.len(),
    );
    for player in &state.players {
        for obj in player.battlefield.iter() {
            refs.push(obj);
        }
    }
    // Stable sort: ties (synthetic-state fixtures with default-0
    // timestamps) preserve the p0-then-p1 walk, keeping pre-CE4
    // baselines bit-equal.
    refs.sort_by_key(|o| o.etb_timestamp);
    refs
}
