//! Win / loss condition primitives on `GameState`.
//!
//! Composes with the round-1 life slice — a player with life <= 0
//! loses (CR 104.3a, simplified). Future slices add the other loss
//! conditions (deck-out 104.3b, poison counters 104.3c, etc.).
//!
//! **Implementation (round-26 G10 + G11 closure).** ``losers`` is
//! computed as the OR of three signals:
//!   - ``Player.has_lost`` — sticky loss flag, never clears once set.
//!     Written by ``apply_sbas()`` when it sees one of the
//!     cause-signals, and by ``lose_game(p)`` for explicit
//!     "you lose the game" effects (Phage / Bargain).
//!   - ``Player.attempted_draw_on_empty`` — cause-signal set by the
//!     empty-library draw path (CR 704.5b). Read here directly so
//!     the loss is observable BEFORE the next SBA pass runs (matches
//!     Python's eager ``p.has_lost = True`` in ``turn.draw_card``).
//!   - ``life <= 0`` — the round-1 derived signal, preserved so the
//!     pure-derivation revival semantics (a 0-life player gaining
//!     life via ``gain_life`` is removed from ``losers()``) still
//!     hold. ``apply_sbas()`` is the only path that transitions this
//!     into the sticky ``has_lost``; without an SBA pass the loss
//!     stays revivable.
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

    /// Python-compatible alias for ``is_game_over``.
    ///
    /// The parity smoke harness (``scripts/parity_smoke.py``) hashes
    /// game state via Python's ``state.is_over()`` API; the Rust
    /// ``GameState`` must expose the same name so the same hashing
    /// code works against either engine. Semantics are identical to
    /// ``is_game_over``: True iff at least one player has life <= 0
    /// (which under pure-derivation includes the simultaneous
    /// double-loss / draw case — a draw is still a finished game).
    ///
    /// Implemented as a thin wrapper rather than a rename so the
    /// existing 19 ``is_game_over``-using winloss tests still pass.
    fn is_over(&self) -> bool {
        self.is_game_over()
    }

    /// Python-property-style accessor: ``state.is_draw`` (NOT
    /// ``state.is_draw()``). Returns True iff BOTH players have
    /// life <= 0 simultaneously — the "mutual lethal damage" case
    /// where neither player can be declared the winner. False
    /// otherwise (game still ongoing OR exactly one player has lost,
    /// in which case ``winner_id`` reports the survivor).
    ///
    /// Pure-derivation caveat (per the module docstring): a 0-life
    /// player can be revived by ``gain_life`` because there is no
    /// SBA loop locking in the loss; so calling
    /// ``set_life(0, 0); set_life(1, 0); gain_life(0, 5)`` flips
    /// ``is_draw`` back to False. The SBA-driven "loss is permanent"
    /// model lands with the explicit-loss field in a future slice.
    #[getter]
    fn is_draw(&self) -> bool {
        let p0 = &self.players[0];
        let p1 = &self.players[1];
        let p0_lost = p0.has_lost || p0.attempted_draw_on_empty || p0.life <= 0;
        let p1_lost = p1.has_lost || p1.attempted_draw_on_empty || p1.life <= 0;
        p0_lost && p1_lost
    }

    /// Python-property-style accessor: ``state.winner_id`` (NOT
    /// ``state.winner_id()``). Returns ``Some(player_id)`` of the
    /// unique winner, or ``None`` when the game is ongoing OR a draw.
    /// Identical semantics to existing ``winner()`` — the rename
    /// matches the Python ``GameState.winner_id`` field, which the
    /// parity smoke harness hashes.
    ///
    /// Implemented as a thin wrapper rather than a rename so the
    /// existing winner-using winloss tests still pass.
    #[getter]
    fn winner_id(&self) -> Option<u8> {
        self.winner()
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
