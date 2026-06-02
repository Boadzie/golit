//! Pure reactive-DAG logic: dirty tracking, topological scheduling, propagation,
//! and memo bookkeeping. No PyO3 here — this module is plain Rust so it can be
//! unit-tested with `cargo test` without linking a Python interpreter.
//!
//! Design contract (see project_scope.md): the kernel owns the *graph and its
//! state*, never the data. Node values (Polars frames, scalars, rendered
//! fragments) live on the Python side; only node ids and `u64` content hashes
//! cross this boundary.
//!
//! ## Performance-critical methods
//!
//! The scheduling loop that runs on every interaction is driven from Python, but
//! the per-node bookkeeping — signature computation, memo checks, epoch
//! management — now lives entirely in Rust via [`Graph::check_node`],
//! [`Graph::commit_node`], [`Graph::skip_node`], and [`Graph::commit_input`].
//! This collapses 4–6 FFI round-trips per node down to 1–2, keeping the
//! per-interaction overhead proportional to the dirty subgraph, not the total
//! graph size.

use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap, VecDeque};
use std::fmt;

// ── FNV-1a constants (matches Python's hashing.py) ──────────────────────────
const FNV_OFFSET: u64 = 1469598103934665603;
const FNV_PRIME: u64 = 1099511628211;

/// FNV-1a fold: combine an ordered slice of `u64` parts into one signature.
///
/// Used for input-signature computation (mixing content hashes of input deps
/// with epochs of upstream deps) and for `signature_hash` (hashing a single
/// input value). Matches the Python `hashing.combine()` exactly — wrapping u64
/// arithmetic in Rust is equivalent to Python's `(… * FNV_PRIME) & ((1<<64)-1)`.
pub fn combine_hashes(parts: &[u64]) -> u64 {
    let mut h = FNV_OFFSET;
    for &part in parts {
        h = (h ^ part).wrapping_mul(FNV_PRIME);
    }
    h
}

/// The role a node plays in the graph. Drives execution/render semantics on the
/// Python side; here it is metadata used for scheduling and introspection.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum NodeKind {
    /// A user input (widget): value supplied by the client, no function body.
    Input,
    /// A data source (e.g. read a CSV); may depend on inputs.
    Source,
    /// A pure transform over upstream nodes.
    Reactive,
    /// A renderable leaf; produces a UI fragment.
    View,
}

impl NodeKind {
    pub fn parse(s: &str) -> Result<NodeKind, GraphError> {
        match s {
            "input" => Ok(NodeKind::Input),
            "source" => Ok(NodeKind::Source),
            "reactive" => Ok(NodeKind::Reactive),
            "view" => Ok(NodeKind::View),
            other => Err(GraphError::BadKind(other.to_string())),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            NodeKind::Input => "input",
            NodeKind::Source => "source",
            NodeKind::Reactive => "reactive",
            NodeKind::View => "view",
        }
    }
}

/// Where a node sits in the propagation pass.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum NodeState {
    /// Up to date; its memoized value is valid.
    Clean,
    /// Needs (re)computation.
    Dirty,
    /// Currently executing (set by the scheduler driver).
    Computing,
}

impl NodeState {
    pub fn as_str(self) -> &'static str {
        match self {
            NodeState::Clean => "clean",
            NodeState::Dirty => "dirty",
            NodeState::Computing => "computing",
        }
    }
}

/// Errors the kernel can surface to the Python layer.
#[derive(Clone, PartialEq, Eq, Debug)]
pub enum GraphError {
    Duplicate(String),
    Unknown(String),
    SelfDependency(String),
    BadKind(String),
    /// A query needing topology was made before `build()`.
    NotBuilt,
    /// `build()` found a cycle; carries the ids still tangled in it.
    Cycle(Vec<String>),
}

impl fmt::Display for GraphError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            GraphError::Duplicate(id) => write!(f, "node already registered: {id:?}"),
            GraphError::Unknown(id) => write!(f, "unknown node: {id:?}"),
            GraphError::SelfDependency(id) => {
                write!(f, "node {id:?} cannot depend on itself")
            }
            GraphError::BadKind(k) => {
                write!(f, "invalid node kind {k:?} (expected input|source|reactive|view)")
            }
            GraphError::NotBuilt => {
                write!(f, "graph has not been built; call build() after registering nodes")
            }
            GraphError::Cycle(ids) => {
                write!(f, "dependency cycle detected involving: {}", ids.join(", "))
            }
        }
    }
}

struct Node {
    id: String,
    kind: NodeKind,
    deps: Vec<usize>,
    dependents: Vec<usize>,
    state: NodeState,
    hash: Option<u64>,
    /// Monotonic version stamp: bumped by `commit_node` / `commit_input` when
    /// the node's value is (re)computed. Downstream nodes use this via
    /// `check_node` to detect upstream changes in O(1) instead of O(rows).
    epoch: u64,
    /// Content hash of an Input-kind node's current value (set from Python via
    /// `set_input_hash`). Used by `check_node` for downstream signature
    /// computation — downstream nodes mix this hash into their input signature.
    input_hash: Option<u64>,
}

/// A reactive directed acyclic graph.
///
/// Lifecycle: `add_node` / `set_deps` to declare the graph, `build()` to
/// validate it is acyclic and cache a topological order, then the hot-path query
/// methods (`check_node`, `commit_node`, `skip_node`, …) on every interaction.
pub struct Graph {
    nodes: Vec<Node>,
    index: HashMap<String, usize>,
    /// Node indices in a stable topological order (computed by `build`).
    topo: Vec<usize>,
    /// `topo_pos[node_idx]` = position of that node within `topo`.
    topo_pos: Vec<usize>,
    built: bool,
    /// Process-monotonic clock shared across all nodes; every `commit_*` call
    /// increments it and stamps the node. Epochs are never reused.
    clock: u64,
}

impl Default for Graph {
    fn default() -> Self {
        Self::new()
    }
}

impl Graph {
    pub fn new() -> Self {
        Graph {
            nodes: Vec::new(),
            index: HashMap::new(),
            topo: Vec::new(),
            topo_pos: Vec::new(),
            built: false,
            clock: 0,
        }
    }

    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    #[allow(dead_code)] // conventional companion to len(); kept for the Rust API
    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    pub fn contains(&self, id: &str) -> bool {
        self.index.contains_key(id)
    }

    fn idx(&self, id: &str) -> Result<usize, GraphError> {
        self.index
            .get(id)
            .copied()
            .ok_or_else(|| GraphError::Unknown(id.to_string()))
    }

    /// Register a node. New nodes start `Dirty` with no memo hash. Declaring a
    /// node (or its deps) invalidates the cached topology.
    pub fn add_node(&mut self, id: &str, kind: &str) -> Result<(), GraphError> {
        if self.index.contains_key(id) {
            return Err(GraphError::Duplicate(id.to_string()));
        }
        let kind = NodeKind::parse(kind)?;
        let i = self.nodes.len();
        self.nodes.push(Node {
            id: id.to_string(),
            kind,
            deps: Vec::new(),
            dependents: Vec::new(),
            state: NodeState::Dirty,
            hash: None,
            epoch: 0,
            input_hash: None,
        });
        self.index.insert(id.to_string(), i);
        self.built = false;
        Ok(())
    }

    /// Set the inbound edges of a node. All deps must already be registered.
    /// Duplicates are collapsed; self-edges are rejected.
    pub fn set_deps(&mut self, id: &str, deps: &[String]) -> Result<(), GraphError> {
        let node_idx = self.idx(id)?;
        let mut resolved: Vec<usize> = Vec::with_capacity(deps.len());
        for d in deps {
            if d == id {
                return Err(GraphError::SelfDependency(id.to_string()));
            }
            let di = self.idx(d)?;
            if !resolved.contains(&di) {
                resolved.push(di);
            }
        }
        self.nodes[node_idx].deps = resolved;
        self.built = false;
        Ok(())
    }

    /// Validate the graph is acyclic and cache a stable topological order.
    /// Recomputes the dependent lists from `deps`. Preserves node state/hash so
    /// memoization survives a rebuild.
    pub fn build(&mut self) -> Result<(), GraphError> {
        let n = self.nodes.len();
        for node in &mut self.nodes {
            node.dependents.clear();
        }
        // edge dep -> node (dep has `node` as a dependent)
        let edges: Vec<(usize, usize)> = self
            .nodes
            .iter()
            .enumerate()
            .flat_map(|(i, node)| node.deps.iter().map(move |&d| (d, i)))
            .collect();
        for (d, i) in edges {
            self.nodes[d].dependents.push(i);
        }

        // Kahn's algorithm. A min-heap on index yields a deterministic order
        // that respects insertion order among otherwise-ready nodes.
        let mut indeg: Vec<usize> = self.nodes.iter().map(|node| node.deps.len()).collect();
        let mut ready: BinaryHeap<Reverse<usize>> = (0..n)
            .filter(|&i| indeg[i] == 0)
            .map(Reverse)
            .collect();
        let mut order: Vec<usize> = Vec::with_capacity(n);
        while let Some(Reverse(u)) = ready.pop() {
            order.push(u);
            for k in 0..self.nodes[u].dependents.len() {
                let v = self.nodes[u].dependents[k];
                indeg[v] -= 1;
                if indeg[v] == 0 {
                    ready.push(Reverse(v));
                }
            }
        }
        if order.len() < n {
            let tangled: Vec<String> = (0..n)
                .filter(|&i| indeg[i] > 0)
                .map(|i| self.nodes[i].id.clone())
                .collect();
            return Err(GraphError::Cycle(tangled));
        }

        let mut topo_pos = vec![0usize; n];
        for (pos, &idx) in order.iter().enumerate() {
            topo_pos[idx] = pos;
        }
        self.topo = order;
        self.topo_pos = topo_pos;
        self.built = true;
        Ok(())
    }

    fn ensure_built(&self) -> Result<(), GraphError> {
        if self.built {
            Ok(())
        } else {
            Err(GraphError::NotBuilt)
        }
    }

    /// The full build order: every node id, topologically sorted.
    pub fn topo_order(&self) -> Result<Vec<String>, GraphError> {
        self.ensure_built()?;
        Ok(self.topo.iter().map(|&i| self.nodes[i].id.clone()).collect())
    }

    /// Breadth-first closure over dependents starting from `seeds` (seeds
    /// included). Order is arbitrary; callers sort by `topo_pos`.
    fn closure(&self, seeds: &[usize]) -> Vec<usize> {
        let mut seen = vec![false; self.nodes.len()];
        let mut queue: VecDeque<usize> = VecDeque::new();
        for &s in seeds {
            if !seen[s] {
                seen[s] = true;
                queue.push_back(s);
            }
        }
        let mut out = Vec::new();
        while let Some(u) = queue.pop_front() {
            out.push(u);
            for &v in &self.nodes[u].dependents {
                if !seen[v] {
                    seen[v] = true;
                    queue.push_back(v);
                }
            }
        }
        out
    }

    fn resolve_seeds(&self, seeds: &[String]) -> Result<Vec<usize>, GraphError> {
        seeds.iter().map(|s| self.idx(s)).collect()
    }

    fn sorted_ids(&self, mut indices: Vec<usize>) -> Vec<String> {
        indices.sort_by_key(|&i| self.topo_pos[i]);
        indices.into_iter().map(|i| self.nodes[i].id.clone()).collect()
    }

    /// The recompute schedule for a set of changed seeds: the seeds plus every
    /// transitively affected node, in topological order. Pure (no mutation) —
    /// this is the hot path that runs on every interaction.
    pub fn dirty_subgraph(&self, seeds: &[String]) -> Result<Vec<String>, GraphError> {
        self.ensure_built()?;
        let seed_idx = self.resolve_seeds(seeds)?;
        Ok(self.sorted_ids(self.closure(&seed_idx)))
    }

    /// Mark the seeds and everything downstream of them `Dirty`. Returns the
    /// affected ids in topological order.
    pub fn mark_dirty(&mut self, seeds: &[String]) -> Result<Vec<String>, GraphError> {
        self.ensure_built()?;
        let seed_idx = self.resolve_seeds(seeds)?;
        let affected = self.closure(&seed_idx);
        for &i in &affected {
            self.nodes[i].state = NodeState::Dirty;
        }
        Ok(self.sorted_ids(affected))
    }

    /// Nodes strictly downstream of `id` (excluding `id`), topologically
    /// ordered. Used to target which view fragments an invalidation touches.
    pub fn downstream(&self, id: &str) -> Result<Vec<String>, GraphError> {
        self.ensure_built()?;
        let i = self.idx(id)?;
        let closure: Vec<usize> = self.closure(&[i]).into_iter().filter(|&x| x != i).collect();
        Ok(self.sorted_ids(closure))
    }

    /// Memo check: does this node need recomputation given the content hash of
    /// its current inputs? True if the stored hash differs (or is absent).
    pub fn needs_recompute(&self, id: &str, input_hash: u64) -> Result<bool, GraphError> {
        let i = self.idx(id)?;
        Ok(self.nodes[i].hash != Some(input_hash))
    }

    /// Commit a node as clean with the content hash of the inputs it was
    /// computed from (its memo cache key).
    pub fn set_clean(&mut self, id: &str, hash: u64) -> Result<(), GraphError> {
        let i = self.idx(id)?;
        self.nodes[i].state = NodeState::Clean;
        self.nodes[i].hash = Some(hash);
        Ok(())
    }

    pub fn set_computing(&mut self, id: &str) -> Result<(), GraphError> {
        let i = self.idx(id)?;
        self.nodes[i].state = NodeState::Computing;
        Ok(())
    }

    pub fn set_dirty(&mut self, id: &str) -> Result<(), GraphError> {
        let i = self.idx(id)?;
        self.nodes[i].state = NodeState::Dirty;
        Ok(())
    }

    // ── Consolidated hot path ───────────────────────────────────────────────
    //
    // The scheduler driver in `engine.py` walks the dirty subgraph once per
    // interaction. These four methods fold the per-node bookkeeping that used to
    // round-trip through Python — dep iteration, signature folding, the memo
    // check, epoch stamping — into Rust, so the driver crosses the FFI boundary
    // about twice per node (`check_node` then `commit_node`/`skip_node`/`commit_input`)
    // instead of four-to-six times. The signature semantics match the old Python
    // `_input_signature` exactly: an Input dep contributes its content hash
    // (`input_hash`, so reverting a control to a prior value is a memo hit), a
    // computed dep contributes its `epoch` (O(1); a recomputed upstream bumped it).

    /// Fold a node's dependency signature the way the old Python path did:
    /// Input deps by content hash, computed deps by epoch.
    fn signature_of(&self, i: usize) -> u64 {
        let parts: Vec<u64> = self.nodes[i]
            .deps
            .iter()
            .map(|&d| {
                let dep = &self.nodes[d];
                if dep.kind == NodeKind::Input {
                    dep.input_hash.unwrap_or(0)
                } else {
                    dep.epoch
                }
            })
            .collect();
        combine_hashes(&parts)
    }

    /// Per-node decision for the scheduler: returns `(kind, needs_recompute,
    /// signature)`. `needs_recompute` is true when the freshly folded signature
    /// differs from the one stored at the node's last clean commit. Pure — the
    /// driver commits the outcome with `commit_node`/`skip_node`.
    pub fn check_node(&self, id: &str) -> Result<(&'static str, bool, u64), GraphError> {
        let i = self.idx(id)?;
        let sig = self.signature_of(i);
        let needs = self.nodes[i].hash != Some(sig);
        Ok((self.nodes[i].kind.as_str(), needs, sig))
    }

    /// Commit a computed node (source/reactive/view) as clean with the signature
    /// it was computed from, and bump its epoch so downstream nodes recompute.
    pub fn commit_node(&mut self, id: &str, signature: u64) -> Result<(), GraphError> {
        let i = self.idx(id)?;
        self.clock += 1;
        let clock = self.clock;
        let node = &mut self.nodes[i];
        node.state = NodeState::Clean;
        node.hash = Some(signature);
        node.epoch = clock;
        Ok(())
    }

    /// Commit a memo hit: the node's inputs are unchanged, so leave its stored
    /// value and epoch untouched — downstream must *not* see a change.
    pub fn skip_node(&mut self, id: &str, signature: u64) -> Result<(), GraphError> {
        let i = self.idx(id)?;
        let node = &mut self.nodes[i];
        node.state = NodeState::Clean;
        node.hash = Some(signature);
        Ok(())
    }

    /// Record an Input node's current value hash (pushed from Python when the
    /// control changes). Downstream signatures mix this in, so an input reverting
    /// to a previous value yields an identical signature — a genuine memo hit.
    pub fn commit_input(&mut self, id: &str, content_hash: u64) -> Result<(), GraphError> {
        let i = self.idx(id)?;
        let node = &mut self.nodes[i];
        node.input_hash = Some(content_hash);
        node.hash = Some(content_hash);
        node.state = NodeState::Clean;
        Ok(())
    }

    pub fn state_of(&self, id: &str) -> Result<&'static str, GraphError> {
        let i = self.idx(id)?;
        Ok(self.nodes[i].state.as_str())
    }

    pub fn kind_of(&self, id: &str) -> Result<&'static str, GraphError> {
        let i = self.idx(id)?;
        Ok(self.nodes[i].kind.as_str())
    }

    pub fn deps_of(&self, id: &str) -> Result<Vec<String>, GraphError> {
        let i = self.idx(id)?;
        Ok(self.nodes[i].deps.iter().map(|&d| self.nodes[d].id.clone()).collect())
    }

    /// All currently-dirty node ids, topologically ordered.
    pub fn dirty_nodes(&self) -> Result<Vec<String>, GraphError> {
        self.ensure_built()?;
        let dirty: Vec<usize> = self
            .topo
            .iter()
            .copied()
            .filter(|&i| self.nodes[i].state == NodeState::Dirty)
            .collect();
        Ok(dirty.into_iter().map(|i| self.nodes[i].id.clone()).collect())
    }

    /// View-kind node ids in topological order.
    pub fn views(&self) -> Result<Vec<String>, GraphError> {
        self.ensure_built()?;
        Ok(self
            .topo
            .iter()
            .copied()
            .filter(|&i| self.nodes[i].kind == NodeKind::View)
            .map(|i| self.nodes[i].id.clone())
            .collect())
    }

    /// All node ids in insertion order.
    pub fn node_ids(&self) -> Vec<String> {
        self.nodes.iter().map(|node| node.id.clone()).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a graph from (id, kind) nodes and (id, deps) edges.
    fn graph(nodes: &[(&str, &str)], edges: &[(&str, &[&str])]) -> Graph {
        let mut g = Graph::new();
        for (id, kind) in nodes {
            g.add_node(id, kind).unwrap();
        }
        for (id, deps) in edges {
            let deps: Vec<String> = deps.iter().map(|s| s.to_string()).collect();
            g.set_deps(id, &deps).unwrap();
        }
        g.build().unwrap();
        g
    }

    fn ids(v: Vec<String>) -> Vec<String> {
        v
    }

    #[test]
    fn linear_chain_schedules_downstream() {
        // a -> b -> c
        let g = graph(
            &[("a", "input"), ("b", "reactive"), ("c", "view")],
            &[("b", &["a"]), ("c", &["b"])],
        );
        assert_eq!(g.topo_order().unwrap(), vec!["a", "b", "c"]);
        assert_eq!(g.dirty_subgraph(&["a".into()]).unwrap(), vec!["a", "b", "c"]);
        assert_eq!(g.dirty_subgraph(&["b".into()]).unwrap(), vec!["b", "c"]);
        assert_eq!(g.dirty_subgraph(&["c".into()]).unwrap(), vec!["c"]);
        assert_eq!(g.downstream("a").unwrap(), vec!["b", "c"]);
        assert_eq!(g.downstream("c").unwrap(), Vec::<String>::new());
    }

    #[test]
    fn diamond_has_no_duplicate_and_orders_join_last() {
        // a -> b, a -> c, b -> d, c -> d
        let g = graph(
            &[("a", "source"), ("b", "reactive"), ("c", "reactive"), ("d", "view")],
            &[("b", &["a"]), ("c", &["a"]), ("d", &["b", "c"])],
        );
        assert_eq!(g.topo_order().unwrap(), vec!["a", "b", "c", "d"]);
        // d must appear exactly once and after both b and c.
        assert_eq!(g.dirty_subgraph(&["a".into()]).unwrap(), vec!["a", "b", "c", "d"]);
        assert_eq!(g.dirty_subgraph(&["b".into()]).unwrap(), vec!["b", "d"]);
    }

    #[test]
    fn wide_fanout() {
        // a -> b, a -> c, a -> d
        let g = graph(
            &[("a", "input"), ("b", "view"), ("c", "view"), ("d", "view")],
            &[("b", &["a"]), ("c", &["a"]), ("d", &["a"])],
        );
        assert_eq!(g.dirty_subgraph(&["a".into()]).unwrap(), vec!["a", "b", "c", "d"]);
        assert_eq!(g.views().unwrap(), vec!["b", "c", "d"]);
    }

    #[test]
    fn multi_seed_dedups_and_orders() {
        // a -> c, b -> c
        let g = graph(
            &[("a", "input"), ("b", "input"), ("c", "view")],
            &[("c", &["a", "b"])],
        );
        let sched = g.dirty_subgraph(&["a".into(), "b".into()]).unwrap();
        assert_eq!(sched, vec!["a", "b", "c"]);
    }

    #[test]
    fn cycle_is_rejected() {
        let mut g = Graph::new();
        g.add_node("a", "reactive").unwrap();
        g.add_node("b", "reactive").unwrap();
        g.set_deps("a", &["b".into()]).unwrap();
        g.set_deps("b", &["a".into()]).unwrap();
        match g.build() {
            Err(GraphError::Cycle(ids)) => {
                assert!(ids.contains(&"a".to_string()) && ids.contains(&"b".to_string()));
            }
            other => panic!("expected cycle, got {other:?}"),
        }
    }

    #[test]
    fn duplicate_node_rejected() {
        let mut g = Graph::new();
        g.add_node("a", "input").unwrap();
        assert_eq!(g.add_node("a", "view"), Err(GraphError::Duplicate("a".into())));
    }

    #[test]
    fn unknown_dep_rejected() {
        let mut g = Graph::new();
        g.add_node("a", "reactive").unwrap();
        assert_eq!(g.set_deps("a", &["ghost".into()]), Err(GraphError::Unknown("ghost".into())));
    }

    #[test]
    fn self_dependency_rejected() {
        let mut g = Graph::new();
        g.add_node("a", "reactive").unwrap();
        assert_eq!(
            g.set_deps("a", &["a".into()]),
            Err(GraphError::SelfDependency("a".into()))
        );
    }

    #[test]
    fn bad_kind_rejected() {
        let mut g = Graph::new();
        assert_eq!(g.add_node("a", "widget"), Err(GraphError::BadKind("widget".into())));
    }

    #[test]
    fn queries_require_build() {
        let mut g = Graph::new();
        g.add_node("a", "input").unwrap();
        assert_eq!(g.topo_order(), Err(GraphError::NotBuilt));
        assert_eq!(g.dirty_subgraph(&["a".into()]), Err(GraphError::NotBuilt));
    }

    #[test]
    fn memoization_is_hash_based() {
        let g = graph(&[("a", "input")], &[]);
        // No hash yet -> needs recompute.
        assert!(g.needs_recompute("a", 42).unwrap());
        let mut g = g;
        g.set_clean("a", 42).unwrap();
        assert!(!g.needs_recompute("a", 42).unwrap()); // same inputs -> memo hit
        assert!(g.needs_recompute("a", 99).unwrap()); // changed inputs -> recompute
        assert_eq!(g.state_of("a").unwrap(), "clean");
    }

    #[test]
    fn mark_dirty_sets_state_across_closure() {
        let mut g = graph(
            &[("a", "input"), ("b", "reactive"), ("c", "view")],
            &[("b", &["a"]), ("c", &["b"])],
        );
        g.set_clean("a", 1).unwrap();
        g.set_clean("b", 2).unwrap();
        g.set_clean("c", 3).unwrap();
        let affected = g.mark_dirty(&["a".into()]).unwrap();
        assert_eq!(affected, vec!["a", "b", "c"]);
        assert_eq!(g.dirty_nodes().unwrap(), vec!["a", "b", "c"]);
        assert_eq!(g.state_of("c").unwrap(), "dirty");
    }

    #[test]
    fn deps_introspection() {
        let g = graph(
            &[("a", "input"), ("b", "input"), ("c", "view")],
            &[("c", &["a", "b"])],
        );
        assert_eq!(ids(g.deps_of("c").unwrap()), vec!["a", "b"]);
        assert_eq!(g.kind_of("c").unwrap(), "view");
    }

    #[test]
    fn combine_matches_fnv1a_reference() {
        // FNV-1a of the empty sequence is the offset basis.
        assert_eq!(combine_hashes(&[]), FNV_OFFSET);
        // One round of the fold, computed by hand with wrapping arithmetic.
        let expect = (FNV_OFFSET ^ 7u64).wrapping_mul(FNV_PRIME);
        assert_eq!(combine_hashes(&[7]), expect);
    }

    #[test]
    fn check_commit_cycle_drives_memoization() {
        // input a -> reactive b -> view c
        let mut g = graph(
            &[("a", "input"), ("b", "reactive"), ("c", "view")],
            &[("b", &["a"]), ("c", &["b"])],
        );

        // Initial render: stamp the input, then commit each computed node.
        g.commit_input("a", 100).unwrap();
        let (kb, needs_b, sig_b) = g.check_node("b").unwrap();
        assert_eq!(kb, "reactive");
        assert!(needs_b); // never committed -> recompute
        g.commit_node("b", sig_b).unwrap();
        let (_, needs_c, sig_c) = g.check_node("c").unwrap();
        assert!(needs_c);
        g.commit_node("c", sig_c).unwrap();

        // Re-checking with no input change is a memo hit at every node.
        assert!(!g.check_node("b").unwrap().1);
        assert!(!g.check_node("c").unwrap().1);

        // Input changes -> b's signature changes -> b and (via epoch) c recompute.
        g.commit_input("a", 200).unwrap();
        let (_, needs_b2, sig_b2) = g.check_node("b").unwrap();
        assert!(needs_b2);
        assert_ne!(sig_b2, sig_b);
        g.commit_node("b", sig_b2).unwrap(); // bumps b's epoch
        assert!(g.check_node("c").unwrap().1); // c sees the new epoch
    }

    #[test]
    fn input_revert_is_a_memo_hit_via_content_hash() {
        // c depends on input a; a computed dep would use epoch, but an Input dep
        // uses its content hash, so reverting a to a prior value memo-hits.
        let mut g = graph(&[("a", "input"), ("c", "view")], &[("c", &["a"])]);
        g.commit_input("a", 30).unwrap();
        let (_, _, sig0) = g.check_node("c").unwrap();
        g.commit_node("c", sig0).unwrap();

        // Re-commit the *same* content hash: signature is unchanged -> memo hit.
        g.commit_input("a", 30).unwrap();
        assert!(!g.check_node("c").unwrap().1);
        assert_eq!(g.check_node("c").unwrap().2, sig0);
    }

    #[test]
    fn skip_node_does_not_bump_epoch() {
        // a -> b -> c; a memo hit on b must leave c undisturbed.
        let mut g = graph(
            &[("a", "input"), ("b", "reactive"), ("c", "view")],
            &[("b", &["a"]), ("c", &["b"])],
        );
        g.commit_input("a", 1).unwrap();
        let sig_b = g.check_node("b").unwrap().2;
        g.commit_node("b", sig_b).unwrap();
        let sig_c = g.check_node("c").unwrap().2;
        g.commit_node("c", sig_c).unwrap();

        // b is re-checked and skipped (no input change): c's signature is stable.
        g.skip_node("b", sig_b).unwrap();
        assert_eq!(g.check_node("c").unwrap().2, sig_c);
        assert!(!g.check_node("c").unwrap().1);
    }
}
