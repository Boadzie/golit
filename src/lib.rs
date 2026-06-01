//! Golit reactive kernel — Python extension entry point.
//!
//! M0 scaffold: a minimal module that confirms the maturin + PyO3 toolchain
//! produces an importable `golit._golit`. The reactive `Graph` lands in M1.

use pyo3::prelude::*;

/// Version of the compiled Rust kernel.
#[pyfunction]
fn kernel_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pymodule]
fn _golit(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(kernel_version, m)?)?;
    Ok(())
}
