use pyo3::prelude::*;

mod cards;
mod state;

/// Return `std::mem::size_of::<GameObject>()` in bytes. Exposed so
/// the bench script and tests can sanity-check that the POD shape
/// stays small as the field set evolves — adding even one `String`
/// field would multiply the per-zone byte cost by an order of
/// magnitude. Catches that regression at bench time.
#[pyfunction]
fn gameobject_byte_size() -> usize {
    std::mem::size_of::<state::GameObject>()
}

#[pymodule]
fn mtg_bot_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<state::GameState>()?;
    m.add_class::<cards::Registry>()?;
    m.add_function(wrap_pyfunction!(state::make_synthetic_state, m)?)?;
    m.add_function(wrap_pyfunction!(gameobject_byte_size, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
