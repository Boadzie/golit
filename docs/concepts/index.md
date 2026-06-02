# Concepts

The tutorial showed you *how* to build a Golit app. This section explains *why* it works the way it does — the ideas that make updates cost proportional to the change.

You don't need any of this to ship an app. But it's what lets you reason about performance, debug surprising recomputes, and trust the framework under load.

<div class="golit-grid" markdown>

<div markdown>
### [The reactive model](reactivity.md)
Dirty tracking, topological scheduling, and hash-based memoization — the algorithm in the Rust kernel that decides what runs.
</div>

<div markdown>
### [Architecture](architecture.md)
The four tiers, from the Rust kernel up to the Alpine.js local shield, and why each technology was chosen.
</div>

<div markdown>
### [How a change flows](data-flow.md)
A single interaction traced end to end: the two channels (POST in, SSE out) and what travels on the wire.
</div>

</div>

## The one-sentence version

> Golit compiles your app into a dependency graph. When an input changes, a Rust kernel computes the exact set of downstream nodes affected, re-executes only those whose inputs actually changed, and swaps only the UI fragments that those nodes produce.

Everything in this section is an elaboration of that sentence.
