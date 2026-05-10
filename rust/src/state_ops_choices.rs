//! Helpers for "the active player makes a deterministic first-slice
//! choice" — used by effect dispatch and tests. Round-18 slice fills
//! in the body that the foundation just stubbed.
//!
//! The intent: extract the "pick the first card on the defender's
//! battlefield" / "first card in hand" / "top of library" patterns
//! that are duplicated across DealDamage / TapTarget / DestroyTarget /
//! AddCounters / DiscardCard arms in apply_effect into a small set
//! of named primitives. Each picker is a pure (read-only) method on
//! GameState that returns `Option<u32>` (the chosen object id) or
//! `None` when the choice would fizzle. A future slice can then
//! collapse the duplicated arm code onto these helpers without
//! touching cards.rs.
//!
//! **Read-only contract.** None of these helpers call
//! `Arc::make_mut`; they iterate the existing zone Arcs and return an
//! id. Callers that mutate (apply damage, tap the chosen target) are
//! responsible for their own CoW path.
//!
//! **Top of library = last element of the Vec.** This matches the
//! round-1 zone convention (peek_top / pop_top use the last element
//! for O(1) access). Callers that want to read "the top card the
//! player would draw next" use `choose_top_of_library_for_player`.
//!
//! **Out-of-range player_id raises ValueError.** Mirrors the existing
//! life / damage modules, which raise on `player_id >= 2`. A
//! previous draft used IndexError for the same case; the slice spec
//! pins this to ValueError to match the dispatch-error convention.

use crate::state::GameState;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

fn check_player_id(player_id: u8) -> PyResult<usize> {
    let idx = player_id as usize;
    if idx >= 2 {
        return Err(PyValueError::new_err(format!(
            "player_id {player_id} out of range (must be 0 or 1)"
        )));
    }
    Ok(idx)
}

#[pymethods]
impl GameState {
    /// Return the obj_id of the first object on `player_id`'s
    /// battlefield whose printing has "Creature" in `card_types`.
    /// Returns `None` if no such creature exists (empty battlefield
    /// or only non-creature permanents). Raises `ValueError` on an
    /// out-of-range `player_id`.
    fn choose_first_creature_for_player(&self, player_id: u8) -> PyResult<Option<u32>> {
        let idx = check_player_id(player_id)?;
        for obj in self.players[idx].battlefield.iter() {
            if let Some(p) = self.registry.lookup(obj.printing_id) {
                if p.card_types.iter().any(|t| t == "Creature") {
                    return Ok(Some(obj.id));
                }
            }
        }
        Ok(None)
    }

    /// Return the obj_id of the first card in `player_id`'s hand
    /// (`hand[0]`). Returns `None` on empty hand. Raises `ValueError`
    /// on an out-of-range `player_id`.
    fn choose_first_card_in_hand_for_player(
        &self,
        player_id: u8,
    ) -> PyResult<Option<u32>> {
        let idx = check_player_id(player_id)?;
        Ok(self.players[idx].hand.first().map(|obj| obj.id))
    }

    /// Return the obj_id of the top of `player_id`'s library
    /// (`library.last()` per the round-1 top=last convention).
    /// Returns `None` on empty library. Raises `ValueError` on an
    /// out-of-range `player_id`.
    fn choose_top_of_library_for_player(
        &self,
        player_id: u8,
    ) -> PyResult<Option<u32>> {
        let idx = check_player_id(player_id)?;
        Ok(self.players[idx].library.last().map(|obj| obj.id))
    }

    /// Return the obj_id of the first permanent on `player_id`'s
    /// battlefield (`battlefield[0]`), regardless of card type.
    /// Returns `None` on empty battlefield. Raises `ValueError` on
    /// an out-of-range `player_id`.
    fn choose_first_permanent_for_player(
        &self,
        player_id: u8,
    ) -> PyResult<Option<u32>> {
        let idx = check_player_id(player_id)?;
        Ok(self.players[idx].battlefield.first().map(|obj| obj.id))
    }

    /// Convenience wrapper: pick the first creature on the defending
    /// player's (i.e. `1 - active_player`'s) battlefield. Mirrors the
    /// "first creature on defender's bf" pattern in `apply_effect`'s
    /// DealDamage / TapTarget / AddCounters arms. Returns `None` if
    /// the defender has no creature.
    fn choose_first_creature_for_defender(&self) -> PyResult<Option<u32>> {
        let defender = 1 - self.active_player;
        self.choose_first_creature_for_player(defender)
    }
}
