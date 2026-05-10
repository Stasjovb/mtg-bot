use pyo3::prelude::*;

mod cards;
mod state;

#[pymodule]
fn mtg_bot_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<state::GameState>()?;
    m.add_class::<cards::Registry>()?;
    m.add_function(wrap_pyfunction!(state::make_synthetic_state, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
