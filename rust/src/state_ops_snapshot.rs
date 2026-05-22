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
//! **Battlefield ordering (CE4 closure).** `battlefield_snapshot`
//! collects every bf object from both players and emits them in
//! ascending `etb_timestamp` order — matching Python's centralized
//! `state.battlefield` append-order. Stable-sort ties preserve the
//! p0-then-p1 traversal so synthetic-state baselines (which never
//! call `reserve_etb_timestamp` and so leave every object at
//! timestamp 0) stay bit-equal to the pre-CE4 snapshot. Real
//! ETB-driven flows produce strictly-monotonic timestamps (every
//! `reserve_etb_timestamp` bumps the counter), so the sort produces
//! the ETB-interleaved order Python emits.

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
    // **Cast-from-exile-with-cost-hike substrate (Lightstall
    // Inquisitor residue closure).** Surface the persistent
    // permission flag so cross-engine harnesses can see the Rust
    // side stamp it. Pre-substrate snapshot pinned baselines
    // observe `false` on every object (back-compat default --
    // unchanged from the pre-substrate dict), so the new key is
    // additive but the value is invariant on snapshots that don't
    // exercise the Lightstall ETB.
    d.set_item(
        "cast_from_exile_with_lightstall_surcharge",
        obj.cast_from_exile_with_lightstall_surcharge,
    )?;
    // **Aura-attachment Phase 4 S3 closure (2026-05-21).** Surface
    // the per-object Token-supertype override so cross-engine bench
    // probes can observe a Moonlit-Meditation-replacement token's
    // injected "Token" supertype. Pre-substrate snapshots observe
    // `false` on every object (back-compat default — unchanged from
    // the pre-substrate dict), so the new key is additive but the
    // value is invariant on snapshots that don't exercise the
    // Moonlit replacement path. The bridge-truthy comparator
    // (cross_engine.assert_bf_snapshots_byte_equal) reads this
    // key alongside the printing's supertypes to recover the same
    // "is this a Token?" answer Python's `obj.printing.is_token`
    // produces against the `_dc.replace`-injected supertype tuple.
    d.set_item(
        "token_supertype_override",
        obj.token_supertype_override,
    )?;
    // **Control-change-UEOT substrate — Cycle 1 (2026-05-21).**
    // Surface the per-object UEOT controller override so cross-engine
    // harnesses can observe the Rust side stamp it (Cycle 3 wires the
    // Python ↔ Rust round-trip; Cycle 4 mints the override from
    // Mutinous-Massacre / Systems-Override resolution arms). Pre-
    // substrate snapshots observe `None` on every object (back-compat
    // default — unchanged from the pre-substrate dict), so the new
    // key is additive but the value is invariant on snapshots that
    // don't exercise the new mint path.
    //
    // Emitted as Python `None` when no override is active, or as the
    // override controller's player id (`0` or `1`) when set.
    match obj.controller_override {
        Some(pid) => d.set_item("controller_override", pid)?,
        None => d.set_item("controller_override", py.None())?,
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
    /// flat list, ordered by per-object `etb_timestamp` (matching
    /// Python's centralized `state.battlefield` append-order).
    ///
    /// **CE4 closure (this slice).** Pre-CE4 this getter flat-emitted
    /// `players[0].battlefield` followed by `players[1].battlefield`
    /// — controller-grouped order. Python's `state.battlefield` is
    /// one centralized list populated by `state.battlefield.append(card)`
    /// at every ETB site, so its iteration order is monotone in ETB
    /// timestamp. The first observable divergence surfaced on Phase 5
    /// multi-turn smoke when both players had a permanent on the
    /// battlefield (step 28 of the slightly_bigger_deckspec run).
    ///
    /// Post-CE4: we collect refs from both per-player Vecs, then
    /// **stable-sort by `etb_timestamp`** before emitting. The
    /// stable-sort matters for the synthetic-state path: `make_player`
    /// pre-populates each player's battlefield without going through
    /// a `reserve_etb_timestamp` call, so every synthetic-state bf
    /// object has timestamp 0; stable-sort preserves the
    /// p0-then-p1 walk order in that case, keeping pre-CE4 pinned
    /// snapshot baselines bit-equal. Real ETB-driven flows produce
    /// strictly-monotonic timestamps (each `reserve_etb_timestamp`
    /// call bumps the counter), so the sort produces the
    /// ETB-interleaved order Python emits.
    fn battlefield_snapshot<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        // Collect by-reference into a single Vec, sort by
        // (etb_timestamp), then project to per-object dicts in the
        // sorted order. Allocating refs first lets us avoid building
        // the heavier PyDict structures for objects we'd just throw
        // away if the sort moved them — but every entry will be
        // emitted regardless, so the sort allocation is one-shot.
        let mut refs: Vec<&crate::state::GameObject> = Vec::with_capacity(
            self.players[0].battlefield.len() + self.players[1].battlefield.len(),
        );
        for player in &self.players {
            for obj in player.battlefield.iter() {
                refs.push(obj);
            }
        }
        // Stable sort: ties (same `etb_timestamp` — e.g. synthetic
        // states with default-0 timestamps) preserve the
        // p0-then-p1, insertion-order traversal so pre-CE4 baselines
        // stay bit-equal.
        refs.sort_by_key(|obj| obj.etb_timestamp);
        let mut out: Vec<Bound<'py, PyDict>> = Vec::with_capacity(refs.len());
        for obj in refs {
            out.push(object_to_pydict(py, self, obj)?);
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
