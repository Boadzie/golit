# App & nodes

## App

The blueprint. Collects node definitions from the decorators and resolves the dependency graph.

::: golit.app.App

## Node kinds & definitions

::: golit.nodes.NodeKind

::: golit.nodes.NodeDef

::: golit.nodes.Param

::: golit.nodes.inspect_params

## Session

The per-client scheduler driver — a fresh kernel graph + value registry built from the shared `App` blueprint.

::: golit.engine.Session
