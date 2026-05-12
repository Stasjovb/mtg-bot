use pyo3::prelude::*;

#[allow(dead_code)]
mod actions;
mod bf_iter;
mod cards;
mod external_rng;
mod state;

// TDD slices: each file adds one `#[pymethods] impl GameState`
// block scoped to a single feature area. Enabled by the
// `multiple-pymethods` feature flag in Cargo.toml. Empty stubs
// land in this commit; each subsequent feature branch fills in
// its own file without touching the others.
mod state_ops_actions;
mod state_ops_cast;
mod state_ops_choices;
mod state_ops_cleanup;
mod state_ops_combat;
mod state_ops_counters;
mod state_ops_counterspell;
mod state_ops_damage;
mod state_ops_decisions;
mod state_ops_deck;
mod state_ops_fingerprint;
mod state_ops_legal;
mod state_ops_library;
mod state_ops_life;
mod state_ops_mana;
mod state_ops_mulligan;
mod state_ops_priority;
mod state_ops_resolve;
mod state_ops_sba;
mod state_ops_setup;
mod state_ops_snapshot;
mod state_ops_stack;
mod state_ops_steps;
mod state_ops_tap;
mod state_ops_winloss;
mod state_ops_zones;

/// Return `std::mem::size_of::<GameObject>()` in bytes. Exposed so
/// the bench script and tests can sanity-check the per-object shape
/// stays small as the field set evolves — adding even one `String`
/// field would multiply the per-zone byte cost by an order of
/// magnitude. Catches that regression at bench time.
///
/// Round-27 UEOT framework: GameObject grew a
/// `ueot_modifiers: Vec<UeotModifier>` field, adding the Vec's
/// 24-byte heap-handle (ptr + len + cap) to the per-object size.
/// The Vec stays empty-by-default so no heap allocation fires on
/// any object that hasn't seen a UEOT effect; the byte_size
/// regression test should be updated to the new ceiling rather
/// than asserting <=20 (the pre-r27 figure).
#[pyfunction]
fn gameobject_byte_size() -> usize {
    std::mem::size_of::<state::GameObject>()
}

#[pymodule]
fn mtg_bot_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<state::GameState>()?;
    m.add_class::<cards::Registry>()?;
    m.add_function(wrap_pyfunction!(state::make_synthetic_state, m)?)?;
    m.add_function(wrap_pyfunction!(state_ops_setup::make_state, m)?)?;
    m.add_function(wrap_pyfunction!(gameobject_byte_size, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
