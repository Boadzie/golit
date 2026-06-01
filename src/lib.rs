//! Golit reactive kernel — Python extension entry point.
//!
//! Thin PyO3 wrapper over [`core::Graph`]. All graph logic lives in `core` (pure
//! Rust, unit-tested); this layer only marshals types and maps errors to Python
//! exceptions. The reactive `Graph` exposed here is driven by Golit's Python
//! scheduler on every interaction.

mod core;

use pyo3::exceptions::{PyKeyError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;

use crate::core::{Graph as CoreGraph, GraphError};

/// Map a kernel error onto the most fitting Python exception.
fn to_py_err(err: GraphError) -> PyErr {
    let msg = err.to_string();
    match err {
        GraphError::Unknown(_) => PyKeyError::new_err(msg),
        GraphError::NotBuilt => PyRuntimeError::new_err(msg),
        _ => PyValueError::new_err(msg),
    }
}

/// Version of the compiled Rust kernel.
#[pyfunction]
fn kernel_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// A reactive directed acyclic graph: dirty tracking, topological scheduling,
/// propagation, and memo bookkeeping. Holds topology and state only — node
/// values stay on the Python side.
#[pyclass(module = "golit._golit")]
struct Graph {
    inner: CoreGraph,
}

#[pymethods]
impl Graph {
    #[new]
    fn new() -> Self {
        Graph { inner: CoreGraph::new() }
    }

    /// Register a node. `kind` is one of input|source|reactive|view.
    fn add_node(&mut self, id: &str, kind: &str) -> PyResult<()> {
        self.inner.add_node(id, kind).map_err(to_py_err)
    }

    /// Set a node's inbound edges (its dependencies). All deps must exist.
    fn set_deps(&mut self, id: &str, deps: Vec<String>) -> PyResult<()> {
        self.inner.set_deps(id, &deps).map_err(to_py_err)
    }

    /// Validate the graph is acyclic and cache a topological order. Call once
    /// after all nodes and edges are declared.
    fn build(&mut self) -> PyResult<()> {
        self.inner.build().map_err(to_py_err)
    }

    /// Full build order: all node ids, topologically sorted.
    fn topo_order(&self) -> PyResult<Vec<String>> {
        self.inner.topo_order().map_err(to_py_err)
    }

    /// Recompute schedule for changed seeds: the seeds plus all transitively
    /// affected nodes, topologically ordered. Pure — does not mutate state.
    fn dirty_subgraph(&self, seeds: Vec<String>) -> PyResult<Vec<String>> {
        self.inner.dirty_subgraph(&seeds).map_err(to_py_err)
    }

    /// Mark seeds and everything downstream `dirty`; return them topo-ordered.
    fn mark_dirty(&mut self, seeds: Vec<String>) -> PyResult<Vec<String>> {
        self.inner.mark_dirty(&seeds).map_err(to_py_err)
    }

    /// Nodes strictly downstream of `id`, topologically ordered.
    fn downstream(&self, id: &str) -> PyResult<Vec<String>> {
        self.inner.downstream(id).map_err(to_py_err)
    }

    /// Does `id` need recomputation given the content hash of its inputs?
    fn needs_recompute(&self, id: &str, input_hash: u64) -> PyResult<bool> {
        self.inner.needs_recompute(id, input_hash).map_err(to_py_err)
    }

    /// Commit `id` clean with the content hash it was computed from.
    fn set_clean(&mut self, id: &str, hash: u64) -> PyResult<()> {
        self.inner.set_clean(id, hash).map_err(to_py_err)
    }

    fn set_computing(&mut self, id: &str) -> PyResult<()> {
        self.inner.set_computing(id).map_err(to_py_err)
    }

    fn set_dirty(&mut self, id: &str) -> PyResult<()> {
        self.inner.set_dirty(id).map_err(to_py_err)
    }

    fn state_of(&self, id: &str) -> PyResult<&'static str> {
        self.inner.state_of(id).map_err(to_py_err)
    }

    fn kind_of(&self, id: &str) -> PyResult<&'static str> {
        self.inner.kind_of(id).map_err(to_py_err)
    }

    fn deps_of(&self, id: &str) -> PyResult<Vec<String>> {
        self.inner.deps_of(id).map_err(to_py_err)
    }

    /// All currently-dirty node ids, topologically ordered.
    fn dirty_nodes(&self) -> PyResult<Vec<String>> {
        self.inner.dirty_nodes().map_err(to_py_err)
    }

    /// View-kind node ids in topological order.
    fn views(&self) -> PyResult<Vec<String>> {
        self.inner.views().map_err(to_py_err)
    }

    /// All node ids in insertion order.
    fn node_ids(&self) -> Vec<String> {
        self.inner.node_ids()
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }

    fn __contains__(&self, id: &str) -> bool {
        self.inner.contains(id)
    }

    fn __repr__(&self) -> String {
        format!("<golit.Graph nodes={}>", self.inner.len())
    }
}

#[pymodule]
fn _golit(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(kernel_version, m)?)?;
    m.add_class::<Graph>()?;
    Ok(())
}
