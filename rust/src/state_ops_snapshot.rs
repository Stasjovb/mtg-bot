//! Read-only zone snapshot getters on `GameState`.
//!
//! Round-21 phase-2 slice. The parity smoke
//! (`scripts/parity_smoke.py`) hashes a Python `GameState` by walking
//! each zone and projecting every object to a tuple of
//! gameplay-relevant fields (printing name, tapped, summoning_sick,
//! damage, counters, controller_id, id). To compare a Rust
//! `GameState` to a Python one byte-for-byte, the harness needs the
//! same projection for the Rust side. These getters provide it: each
//! returns a Python list of dicts (or one dict for `mana_pool`)
//! whose shape exactly matches what `_zone_signature` reads.
//!
//! **Read-only contract.** None of these methods call
//! `Arc::make_mut`; they iterate the existing zone Arcs and copy
//! per-object fields into freshly-allocated Python dicts. Mutating a
//! returned dict on the Python side is fine — the dict is owned by
//! Python; the Rust state stays untouched.
//!
//! **Per-object dict shape** (matches `parity_smoke.py:_zone_signature`):
//!
//! - `id: int` — GameObject's `.id`.
//! - `printing_id: int`.
//! - `printing_name: str` — registry lookup; falls back to `""` when
//!   the printing is missing (defensive — Python's `_zone_signature`
//!   uses `getattr(obj.printing, "name", None)` which is `None` for
//!   the same edge case; we use `""` because Rust's typed string
//!   field can't carry `None`, and the parity-side hash treats the
//!   two equivalently for this edge case once both sides agree to
//!   emit a sentinel).
//! - `tapped: bool`.
//! - `summoning_sick: bool`.
//! - `damage: int`.
//! - `counters: int`.
//! - `controller_id: int`.
//! - `zone: int` (the u8 zone constant — `ZONE_HAND` / `ZONE_LIBRARY`
//!   / `ZONE_BATTLEFIELD` / `ZONE_GRAVEYARD` / `ZONE_EXILE`).
//!
//! **Battlefield ordering caveat.** `battlefield_snapshot` returns
//! player 0's battlefield in zone-insertion order followed by player
//! 1's battlefield in zone-insertion order. Python's
//! `state.battlefield` is centralized on `GameState` and ordered by
//! ETB timestamp across both players, so Rust's by-player split won't
//! match Python's interleaved ordering whenever a p1 permanent ETB'd
//! between two p0 permanents (or vice versa). Phase 5 work is to
//! align Rust's iteration order with Python's centralized
//! ETB-timestamp order; the parity harness's first divergence will
//! surface this naturally.

use crate::state::GameState;
use pyo3::exceptions::PyIndexError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

fn check_player_id(player_id: u8) -> PyResult<usize> {
    let idx = player_id as usize;
    if idx >= 2 {
        return Err(PyIndexError::new_err(format!(
            "player_id {player_id} out of range (must be 0 or 1)"
        )));
    }
    Ok(idx)
}

/// Project a single `GameObject` into a Python dict. Looks the
/// printing up in `state.registry`; if the printing is missing
/// (synthetic / inconsistent state) `printing_name` falls back to
/// `""` rather than raising — see module docstring.
fn object_to_pydict<'py>(
    py: Python<'py>,
    state: &GameState,
    obj: &crate::state::GameObject,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("id", obj.id)?;
    d.set_item("printing_id", obj.printing_id)?;
    let name = state
        .registry
        .lookup(obj.printing_id)
        .map(|p| p.name.to_string())
        .unwrap_or_default();
    d.set_item("printing_name", name)?;
    d.set_item("tapped", obj.tapped)?;
    d.set_item("summoning_sick", obj.summoning_sick)?;
    d.set_item("damage", obj.damage)?;
    d.set_item("counters", obj.counters)?;
    d.set_item("controller_id", obj.controller)?;
    d.set_item("zone", obj.zone)?;
    // Round-28 attach foundation: mirrors Python's
    // GameObject.attached_to slot. Emitted as Python None when
    // unattached (the default), or as the target id when attached.
    match obj.attached_to {
        Some(id) => d.set_item("attached_to", id)?,
        None => d.set_item("attached_to", py.None())?,
    }
    Ok(d)
}

#[pymethods]
impl GameState {
    /// Snapshot of `player_id`'s hand as a list of per-object dicts
    /// in zone-insertion order. Raises `IndexError` on an out-of-range
    /// `player_id`.
    fn hand_snapshot<'py>(
        &self,
        py: Python<'py>,
        player_id: u8,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let idx = check_player_id(player_id)?;
        self.players[idx]
            .hand
            .iter()
            .map(|obj| object_to_pydict(py, self, obj))
            .collect()
    }

    /// Snapshot of `player_id`'s library as a list of per-object
    /// dicts in zone-insertion order (bottom-of-library first; top
    /// = last per the round-1 convention). Raises `IndexError` on an
    /// out-of-range `player_id`.
    fn library_snapshot<'py>(
        &self,
        py: Python<'py>,
        player_id: u8,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let idx = check_player_id(player_id)?;
        self.players[idx]
            .library
            .iter()
            .map(|obj| object_to_pydict(py, self, obj))
            .collect()
    }

    /// Snapshot of `player_id`'s graveyard as a list of per-object
    /// dicts in zone-insertion order (oldest first). Raises
    /// `IndexError` on an out-of-range `player_id`.
    fn graveyard_snapshot<'py>(
        &self,
        py: Python<'py>,
        player_id: u8,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let idx = check_player_id(player_id)?;
        self.players[idx]
            .graveyard
            .iter()
            .map(|obj| object_to_pydict(py, self, obj))
            .collect()
    }

    /// Snapshot of `player_id`'s exile zone as a list of per-object
    /// dicts in zone-insertion order. Raises `IndexError` on an
    /// out-of-range `player_id`.
    fn exile_snapshot<'py>(
        &self,
        py: Python<'py>,
        player_id: u8,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let idx = check_player_id(player_id)?;
        self.players[idx]
            .exile
            .iter()
            .map(|obj| object_to_pydict(py, self, obj))
            .collect()
    }

    /// Snapshot of BOTH players' battlefields combined into a single
    /// flat list. Order: player 0's battlefield in zone-insertion
    /// order, then player 1's battlefield in zone-insertion order.
    ///
    /// **Phase 5: align battlefield iteration order with Python's
    /// centralized ETB-timestamp order.** Python's
    /// `state.battlefield` is one centralized list ordered by ETB
    /// timestamp across both players; this Rust by-player-split
    /// projection diverges whenever the two players' ETB events
    /// interleave. The parity harness will surface this naturally
    /// the first time a p1 permanent ETBs between two p0
    /// permanents — at that point Phase 5 reorders Rust's
    /// emission (or refactors the underlying Rust battlefield
    /// representation) to match Python.
    fn battlefield_snapshot<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let mut out: Vec<Bound<'py, PyDict>> =
            Vec::with_capacity(self.players[0].battlefield.len() + self.players[1].battlefield.len());
        for player in &self.players {
            for obj in player.battlefield.iter() {
                out.push(object_to_pydict(py, self, obj)?);
            }
        }
        Ok(out)
    }

    /// Snapshot of `player_id`'s mana pool as a 6-key dict
    /// `{"W", "U", "B", "R", "G", "C"}` mapping each color to its
    /// current count. Always returns all six keys, mirroring the
    /// existing `get_mana_pool` shape so Python callers can rely on
    /// `.get(color, 0)` not being needed. Raises `IndexError` on an
    /// out-of-range `player_id`.
    fn mana_pool_snapshot<'py>(
        &self,
        py: Python<'py>,
        player_id: u8,
    ) -> PyResult<Bound<'py, PyDict>> {
        let idx = check_player_id(player_id)?;
        let pool = &self.players[idx].mana_pool;
        let d = PyDict::new(py);
        d.set_item("W", pool.white)?;
        d.set_item("U", pool.blue)?;
        d.set_item("B", pool.black)?;
        d.set_item("R", pool.red)?;
        d.set_item("G", pool.green)?;
        d.set_item("C", pool.colorless)?;
        Ok(d)
    }
}
