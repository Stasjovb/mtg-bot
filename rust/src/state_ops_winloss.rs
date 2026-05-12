//! Win / loss condition primitives on `GameState`.
//!
//! Composes with the round-1 life slice — a player with life <= 0
//! loses (CR 104.3a, simplified). Future slices add the other loss
//! conditions (deck-out 104.3b, poison counters 104.3c, etc.).
//!
//! **Implementation (round-26 G10 + G11 closure, refined by CE10
//! CE-pure-derivation-is_over).** Two layers of accessors, with
//! distinct sources of truth:
//!
//! 1. **Eager / cause-flags-driven (Rust-native API).** ``losers()``,
//!    ``winner()``, ``is_game_over()``, ``is_player_alive()`` —
//!    computed as the OR of three signals on each player:
//!      - ``Player.has_lost`` — sticky loss flag, never clears once
//!        set. Written by ``apply_sbas()`` when it sees one of the
//!        cause-signals, and by ``lose_game(p)`` for explicit
//!        "you lose the game" effects (Phage / Bargain).
//!      - ``Player.attempted_draw_on_empty`` — cause-signal set by
//!        the empty-library draw path (CR 704.5b). Read here directly
//!        so the loss is observable BEFORE the next SBA pass runs
//!        (matches Python's eager ``p.has_lost = True`` in
//!        ``turn.draw_card``).
//!      - ``life <= 0`` — the round-1 derived signal, preserved so
//!        the pure-derivation revival semantics (a 0-life player
//!        gaining life via ``gain_life`` is removed from ``losers()``)
//!        still hold. ``apply_sbas()`` is the only path that transitions
//!        this into the sticky ``has_lost``; without an SBA pass the
//!        loss stays revivable.
//!
//! 2. **SBA-gated / Python-named API.** ``is_over()``,
//!    ``state.winner_id`` (getter), ``state.is_draw`` (getter) —
//!    read ONLY from the sticky ``has_lost`` flag. These mirror
//!    Python's ``GameState.is_over`` / ``winner_id`` / ``is_draw``
//!    exactly: Python's ``winner_id`` and ``is_draw`` are written
//!    only by the SBA pass (``turn.apply_state_based_actions``),
//!    and ``is_over`` reads them. The eager cause-flags are
//!    observable on the Python ``Player`` object directly, not via
//!    these surface accessors.
//!
//! **Why the split (CE10 closure).** The cross-engine smoke harness
//! (``tests/test_parity_smoke*.py``) does NOT fire SBAs between
//! decision steps. Pre-CE10, Rust's ``is_over`` / ``winner_id`` used
//! the eager OR'd-three predicate while Python's stayed stale until
//! an SBA pass, surfacing a NOVEL divergence on empty-library draws.
//! Splitting the two API layers makes Rust's surface accessors
//! observably-equivalent to Python while keeping the eager Rust-native
//! API for callers that genuinely need to detect cause-flags-driven
//! loss before SBA runs (notably ``apply_sbas`` itself, which scans
//! both cause-flags to decide whom to flag with ``has_lost``).
//!
//! **Winner semantics in a 2-player game.**
//! - 0 losers -> winner = None (game ongoing).
//! - exactly 1 loser, the OTHER player not also a loser -> winner =
//!   Some(other_player_id).
//! - 2 losers (e.g. mutual lethal damage) -> winner = None
//!   (the "draw" case under pure-derivation semantics).
//!
//! **Pure-derivation caveat for life-back-above-zero.** Real MTG would
//! fire the loss SBA the moment life drops to 0, which would lock in
//! the loss before any subsequent gain_life can revive the player. In
//! this slice there is no SBA loop, so calling ``gain_life`` on a
//! 0-life player does take them out of ``losers()``. The SBA-driven
//! "loss is permanent" model lands with the explicit-loss field in a
//! future slice.

use crate::state::GameState;
use pyo3::exceptions::PyIndexError;
use pyo3::prelude::*;

fn check_player_id(player_id: u8) -> PyResult<usize> {
    let idx = player_id as usize;
    if idx >= 2 {
        return Err(PyIndexError::new_err(format!(
            "player_id {player_id} out of range (must be 0 or 1)"
        )));
    }
    Ok(idx)
}

#[pymethods]
impl GameState {
    /// Return the list of player ids currently in a losing state.
    /// Sorted by player id (0 before 1) for deterministic output.
    ///
    /// Loss predicate (round-26 G10 + G11): a player is a loser iff
    /// any of the following are true:
    ///   - ``has_lost == true`` (sticky flag, set by SBA pass or
    ///     explicit ``lose_game``)
    ///   - ``attempted_draw_on_empty == true`` (CR 704.5b cause-signal
    ///     — read directly so the loss surfaces before the next SBA
    ///     pass, mirroring Python's eager ``p.has_lost = True`` in
    ///     ``turn.draw_card``)
    ///   - ``life <= 0`` (pure-derivation, preserved so the existing
    ///     revival semantics around ``gain_life`` from 0 still hold)
    fn losers(&self) -> Vec<u8> {
        let mut out = Vec::new();
        for p in &self.players {
            if p.has_lost || p.attempted_draw_on_empty || p.life <= 0 {
                out.push(p.id);
            }
        }
        out
    }

    /// Return ``Some(player_id)`` of the unique winner, else ``None``.
    /// Winner is the unique non-loser when exactly one player has
    /// lost. ``None`` when no losers (game ongoing) or when both
    /// players have lost (draw).
    fn winner(&self) -> Option<u8> {
        // Uses the same OR'd-three predicate as `losers()` so the
        // two stay in lockstep.
        let p0 = &self.players[0];
        let p1 = &self.players[1];
        let p0_lost = p0.has_lost || p0.attempted_draw_on_empty || p0.life <= 0;
        let p1_lost = p1.has_lost || p1.attempted_draw_on_empty || p1.life <= 0;
        match (p0_lost, p1_lost) {
            (false, true) => Some(p0.id),
            (true, false) => Some(p1.id),
            // (false, false): no loss yet.
            // (true, true):  simultaneous loss -> no winner.
            _ => None,
        }
    }

    /// True iff at least one player has lost. Uses the same
    /// OR'd-three predicate as `losers()` (has_lost OR
    /// attempted_draw_on_empty OR life <= 0). "Game over" includes
    /// the simultaneous double-loss case (a draw is still a
    /// finished game).
    fn is_game_over(&self) -> bool {
        let p0 = &self.players[0];
        let p1 = &self.players[1];
        p0.has_lost || p0.attempted_draw_on_empty || p0.life <= 0
            || p1.has_lost || p1.attempted_draw_on_empty || p1.life <= 0
    }

    /// True iff ``player_id`` is not in a losing state — the OR'd-three
    /// predicate (NOT has_lost AND NOT attempted_draw_on_empty AND
    /// life > 0). Raises ``IndexError`` if ``player_id`` is not 0 or 1.
    fn is_player_alive(&self, player_id: u8) -> PyResult<bool> {
        let idx = check_player_id(player_id)?;
        let p = &self.players[idx];
        Ok(!p.has_lost && !p.attempted_draw_on_empty && p.life > 0)
    }

    /// Python-named outcome accessor — SBA-GATED (matches Python's
    /// ``GameState.is_over``).
    ///
    /// Python's ``GameState.is_over`` reads ``winner_id is not None or
    /// self.is_draw``; both fields are written ONLY by the
    /// ``apply_state_based_actions`` pass (``turn.py``, lines
    /// 1384-1392). Cause-flags (``Player.has_lost`` set by
    /// ``turn.draw_card``, ``life <= 0`` from damage) are eagerly
    /// observable on Python's ``Player`` objects but DO NOT flip
    /// ``is_over`` until SBA runs.
    ///
    /// **CE-pure-derivation-is_over closure (CE10, this slice):** the
    /// pre-closure Rust implementation read the same OR'd-three
    /// predicate as ``is_game_over`` (cause-flags-driven, eager). The
    /// cross-engine smoke harness in ``tests/test_parity_smoke*.py``
    /// does NOT fire SBAs between steps, so an empty-library
    /// side-channel ``draw_card`` left Python at
    /// ``is_over=False / winner_id=None`` and Rust at
    /// ``is_over=True / winner_id=1`` — the two engines disagreed on
    /// the surface field even though the underlying cause-flags
    /// agreed. Pinned by
    /// ``tests/test_parity_smoke_edge_cases.py::test_cross_engine_empty_library_side_channel_draw_walks_clean``
    /// and ``::test_cross_engine_single_card_libraries_multi_turn_walks_clean``.
    ///
    /// Post-closure: ``is_over`` reads ONLY from the sticky
    /// ``has_lost`` flag on each player (the same source ``winner_id``
    /// and ``is_draw`` now read from). Result: at least one player
    /// has ``has_lost == true``. To get the eager pure-derivation
    /// predicate ("any of the OR'd-three on any player"), use
    /// ``is_game_over()`` — it kept the pre-closure semantics so the
    /// pre-existing 19 winloss tests still pass.
    ///
    /// **Caller migration.** Most callers want SBA-gated outcome
    /// semantics (matches Python, matches the parity smoke harness's
    /// expectations). Callers that need eager loss observability —
    /// for example, internal Rust paths inside ``apply_sbas`` itself
    /// that need to know which players to flag — should use
    /// ``losers()`` or ``is_game_over()`` directly.
    fn is_over(&self) -> bool {
        self.players[0].has_lost || self.players[1].has_lost
    }

    /// Python-property-style accessor: ``state.is_draw`` (NOT
    /// ``state.is_draw()``) — SBA-GATED.
    ///
    /// Python's ``GameState.is_draw`` is a plain ``bool`` field
    /// written ONLY by the ``apply_state_based_actions`` pass when
    /// it observes zero alive players (every ``Player.has_lost`` is
    /// True). Post-CE10 closure (CE-pure-derivation-is_over), Rust's
    /// getter mirrors that: True iff BOTH players have ``has_lost ==
    /// true``. False otherwise.
    ///
    /// To get the eager pure-derivation predicate (the pre-closure
    /// semantics: BOTH players satisfy ``has_lost ||
    /// attempted_draw_on_empty || life <= 0``), there is no direct
    /// helper; combine ``losers() == [0, 1]`` with the loser count if
    /// needed.
    #[getter]
    fn is_draw(&self) -> bool {
        self.players[0].has_lost && self.players[1].has_lost
    }

    /// Python-property-style accessor: ``state.winner_id`` (NOT
    /// ``state.winner_id()``) — SBA-GATED.
    ///
    /// Python's ``GameState.winner_id`` is an ``Optional[int]`` field
    /// written ONLY by the ``apply_state_based_actions`` pass when it
    /// observes exactly one alive player (the OTHER player carries
    /// ``has_lost == true``). Post-CE10 closure
    /// (CE-pure-derivation-is_over), Rust's getter mirrors that:
    /// returns ``Some(other_id)`` when exactly one player has
    /// ``has_lost == true``; returns ``None`` when neither has lost
    /// (game ongoing) OR both have lost (draw).
    ///
    /// To get the eager pure-derivation winner (the pre-closure
    /// semantics — cause-flags-driven, eager), use ``winner()``,
    /// which kept the OR'd-three predicate so the pre-existing tests
    /// still pass.
    #[getter]
    fn winner_id(&self) -> Option<u8> {
        let p0 = &self.players[0];
        let p1 = &self.players[1];
        match (p0.has_lost, p1.has_lost) {
            (false, true) => Some(p0.id),
            (true, false) => Some(p1.id),
            // (false, false): no SBA-committed loss yet.
            // (true, true):  simultaneous loss -> no winner (draw).
            _ => None,
        }
    }

    /// Explicit "you lose the game" primitive (Phage the Untouchable,
    /// Bargain, "lose the game" cards, deck-out post-SBA). Sets the
    /// sticky `has_lost` flag — irrevocable once set, no `gain_life`
    /// can undo it. Round-26 G11 closure.
    ///
    /// Raises `IndexError` if `player_id` is not 0 or 1.
    fn lose_game(&mut self, player_id: u8) -> PyResult<()> {
        let idx = check_player_id(player_id)?;
        self.players[idx].has_lost = true;
        Ok(())
    }
}
