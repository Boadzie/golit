# Golit benchmarks

The performance claim is the whole pitch: **update cost is proportional to the
change, not the program.** This harness proves it. See
[`../golit_benchmark.md`](../golit_benchmark.md) for the full methodology.

## B1 — incremental update latency (the core claim)

> If B1 doesn't show a clear flat-vs-climbing separation, stop and rethink the
> claim before publishing anything. — `golit_benchmark.md`

This is the **internal** B1: Golit measured against itself, before the
cross-framework bake-off (Streamlit / Marimo / Dash) of the published version.
It answers the only question that gates everything else — *is Golit's own update
curve flat as the graph grows?* If it isn't, no comparison matters.

### What it measures

A [synthetic app](gen_app.py) with three independent knobs:

| Knob | Meaning | Swept over |
| --- | --- | --- |
| `rows` | dataset size (per-node compute cost) | 10K, 100K |
| `depth` | length of the **affected chain** the slider feeds | 1, 3, 10 |
| `unaffected` | nodes depending only on `data`, never in the dirty subgraph | 0 … 256 |

```
data ─┬─> r0(threshold) ─> r1 ─> … ─> r{depth-1} ─> chart   ← the slider dirties this
      ├─> u0  ┐
      ├─> u1  │  unaffected: recomputed on a full render,
      └─> …   ┘  but a slider move never touches them
```

For each shape we record three latencies ([instrument.py](instrument.py)):

- **update** — `Session.update` wall time: input change → fragments ready. The
  real server-side metric, reported p50/p95/p99 over many warm iterations (two
  slider values are cycled so every update is a genuine recompute, never a memo
  hit).
- **schedule** — the pure Rust `dirty_subgraph` call in isolation, so we can see
  the kernel's scheduling cost as the *total* graph grows.
- **full** — a full graph recompute (`initial_render` forces every node): the
  naive "rerun everything" baseline a non-reactive framework pays.

The harness also reads `exec_count` straight off the ledger — the number of node
functions the dirty subgraph actually ran. On a slider move it equals
`depth + 1` regardless of how many unaffected nodes exist. That integer *is* the
thesis, before any timer.

### Run it

```bash
make bench           # in-process + HTTP sweeps + both charts  (≈1 min)
make bench-quick     # fast in-process signal                  (≈4 s)
make bench-http      # end-to-end HTTP only

# or directly:
uv run --no-sync python -m bench.run_b1            # in-process -> results/b1.csv
uv run --no-sync python -m bench.http.run_b1_http  # end-to-end -> results/b1_http.csv
uv run --no-sync python -m bench.plot              # both -> results/*_hero.svg
```

Outputs land in [`results/`](results/): `b1.csv` / `b1_http.csv` (every percentile
for every configuration) and `b1_hero.svg` / `b1_http_hero.svg` (the charts,
rendered through Golit's own Lets-Plot → static-SVG path — the same way the
framework draws charts).

## B1 over HTTP — end-to-end (`bench/http/`)

The in-process sweep isolates the *engine*. This one drives Golit's **real POST
transport** to prove the flat curve survives the wire. For each shape it boots an
isolated uvicorn server ([`serve.py`](http/serve.py), graph shape from env), waits
for the port, then a single sequential client ([`drive.py`](http/drive.py)) hammers
`POST /node/threshold` over loopback — timing each input → fragment round-trip
(HTTP framing + ASGI + dirty subgraph + render + the HTMX out-of-band swap body).

It also records **bytes-per-update** — that's **B3** (payload/bandwidth), almost
for free, since every response *is* the fragment on the wire.

What it confirms (100K-row dataset, dev laptop, loopback):

- End-to-end p99 is **flat in unaffected-node count** at every depth — the engine
  result holds through real transport (depth-10 e2e p99 ≈ 0.84 ms). Transport adds a
  roughly *constant* ~0.5 ms over the in-process number; it does not scale with graph
  size. (Since the in-process floor is now ~0.25 ms after the epoch-memo fix below,
  HTTP framing + ASGI is the larger share end-to-end — still flat, still constant.)
- **177 bytes per update, constant** regardless of graph size — only the changed
  chart fragment crosses the wire, and no client charting runtime boots. That's
  the B3 story in one number.

This is still single-client sequential latency (B1), over **loopback**, on a
laptop. **B2** (concurrency / many simultaneous sessions) is the next section;
real network RTT and a cloud instance are the remaining publishable pieces.

### Reading the hero chart

`x` = unaffected nodes, `y` = update p99 (log scale). Golit's three `update`
lines (one per depth) run **flat** near the floor; the `full recompute` line
**climbs** linearly with the graph. Flat-vs-climbing in one picture is the
argument.

The `update` lines are separated by *depth*, not by *unaffected count* — cost
tracks the affected chain that re-executes, exactly as claimed.

In-process wall-clock here is `Session.update` — it excludes HTTP, the HTMX swap,
and SVG rendering. That's intentional: it isolates the reactive engine, the claim
under test. The end-to-end figures (above) add the transport back in.

## Golit vs Streamlit — the head-to-head

The first rival. [`apps/streamlit_app.py`](apps/streamlit_app.py) is the
**behavioral twin** of the synthetic Golit app, written the way a competent
Streamlit dev would — `@st.cache_data` on the data load and the independent
aggregations (the *fair fight*; comparing against an uncached Streamlit would be
rigged). The one thing left uncached is the slider-driven chain, because it
genuinely must recompute each interaction in both frameworks.

[`run_b1_streamlit.py`](run_b1_streamlit.py) drives it via Streamlit's official
`AppTest` harness, which runs the script in-process and excludes the browser
websocket — so it measures Streamlit's **server-side script-rerun**, the same axis
as Golit's in-process `Session.update`. (`AppTest` adds a fixed per-call overhead
that is *constant* in unaffected-node count, so the **slope** — climb vs flat — is
the load-bearing comparison, not the absolute ms.)

Needs the `bench` dependency group: `uv pip install 'streamlit>=1.40'`. Then
`make bench-streamlit` → `results/b1_streamlit.csv` + `results/b1_compare_hero.svg`.

The result (100K rows, depth 3, dev laptop):

| unaffected nodes | Golit update p50 | Streamlit rerun p50 |
| ---: | ---: | ---: |
| 0   | ~0.79 ms | 1.52 ms |
| 64  | ~0.79 ms | 2.55 ms |
| 256 | ~0.80 ms | 5.96 ms |

Golit is **flat**; Streamlit **climbs ~3.9×** across the sweep and the gap widens
without bound — because even cache *hits* cost Streamlit ~17 µs per node it cannot
skip (it reruns the whole script), while Golit never schedules those nodes at all.
That divergence — flat vs climbing — is the pitch, and it survives the fairest
Streamlit we can write.

## Golit vs Marimo — the reactive-vs-reactive test (the honest one)

Marimo is the rival that **shares Golit's thesis**: it's a reactive notebook, so a
slider move re-runs only the cells that transitively depend on it — not the whole
script. Including it isn't optional; it's the comparison that tests Golit's *floor*
rather than just "reactive beats rerun-everything."

[`run_b1_marimo.py`](run_b1_marimo.py) drives marimo's **own** reactive machinery
headless — no `app.run()` (that reruns everything, which would be the Streamlit
story by mistake). On each slider move it calls marimo's real
`dataflow.transitive_closure` (the descendants of the slider's cell — marimo's dirty
subgraph, the analog of Golit's Rust `dirty_subgraph`) and runs exactly that set
through marimo's real `executor.execute_cell`. The notebook itself
([`apps/marimo_gen.py`](apps/marimo_gen.py)) is the behavioral twin — same
`data → r0(threshold) → … → chart` chain plus `unaffected` cells on `data` only.

It measures `slider._update(v)` + scheduling + execution — *decide what to run, then
run it* — the same server-side axis as Golit's `Session.update` and the Streamlit
`AppTest` number. It excludes the browser websocket **and** marimo's kernel
messaging/hook overhead (bare executor, `NoopStream`), so this is marimo's *best
case* — the steelman, just like caching Streamlit.

**Both are flat** — and that's the first thing that matters. Marimo's `exec` count
stays `depth + 1` across `unaffected` 0 → 256, exactly like Golit's. The core thesis
(*cost ∝ change*) is confirmed by a **second, independent** reactive engine; only the
rerun-everything frameworks (Streamlit, Dash) climb. `b1_compare_hero.svg` shows it
in one picture: two flat lines (Golit, Marimo) and one climbing (Streamlit),
log-scaled.

The *floor* is the second thing — and this is where the comparison earned its keep.

| depth | raw Polars | Marimo (reactive) | Golit **before** | Golit **after** |
| ---: | ---: | ---: | ---: | ---: |
| 1  | 0.07 ms | 0.09 ms | 0.42 ms | **0.09 ms** |
| 3  | 0.11 ms | 0.13 ms | 0.72 ms | **0.12 ms** |
| 10 | 0.23 ms | 0.28 ms | 1.86 ms | **0.27 ms** |

When the rival first ran, Golit sat **~5–6× above** Marimo and the raw-Polars floor.
Profiling `Session.update` (cProfile + an isolated micro-bench + an ablation) put the
entire gap on one line: `DataFrame.hash_rows()` — the memo path was **content-hashing
every intermediate frame** (O(rows), ~74% of update time, and on a 62K-row frame a
single hash cost 92 µs vs 35 µs to just *recompute* the node). For cheap-to-recompute
nodes, content-hash memoization costs more than the work it guards.

So the memo was rebuilt to be O(1) (see `python/golit/engine.py` +
`registry.py`): a node's input signature now mixes the **content hash of its scalar
inputs** (cheap, and still catches a control reverting to a prior value) with the
**epochs of its upstream nodes** — an upstream that recomputed bumped its epoch, so a
downstream sees the change without anyone hashing a frame. The wire stays minimal
independently: a re-rendered view is diffed as a *string* before it's pushed, so
nothing redundant crosses the transport. That change is the **after** column: Golit
drops onto the Polars floor, level with Marimo (a hair faster at depth 3), with the
flat curve and `exec == depth + 1` both intact (85 tests green).

The honest read, then: **reactivity buys the flat curve — the thesis, which both
engines have — and Golit's floor now matches the other reactive engine's.** The
reactive-vs-reactive bake-off did exactly what a good benchmark should: it found a
real 5–6× cost in the engine and drove the fix. Where Golit's case against Marimo
goes *next* is production — a different axis this in-process micro-bench doesn't
touch: HTTP fragment transport (177 B/update, no client runtime), multi-worker +
Redis fan-out, and concurrency (B2) — versus a single-user notebook kernel. Caveat
kept for fairness: the marimo number is a best case (bare executor, no
kernel/transport), so "level floor" is the honest claim, not "Golit wins the floor."

## Golit vs Dash — the rival that isn't rerun-everything (the corrected one)

Dash is the framework you'd *expect* to be the other rerun-everything rival. It
isn't, and the benchmark says so plainly. Dash's docs are explicit: a callback fires
only when one of its declared `Input` values changes, and only that callback runs —
the layout and data are not re-evaluated. Dash is a **manually-wired reactive DAG**,
much closer to Golit than to Streamlit.

[`apps/dash_app.py`](apps/dash_app.py) is the faithful twin, and the faithfulness is
the point: the slider drives one callback (the affected chain → chart), and the
`unaffected` nodes — which depend only on the static data — are exactly that,
**static layout**, computed once and never re-run. So a slider move fires **one**
callback regardless of how many unaffected nodes exist. [`run_b1_dash.py`](run_b1_dash.py)
drives the callback directly (the documented way to unit-test a Dash callback without
a browser) over cycled slider values — the same *server compute, no transport* axis as
the Marimo cell and Golit's `Session.update`.

**Result: Dash is flat, exec stays 1.** It joins Golit and Marimo on the flat side of
`b1_compare_hero.svg`; only Streamlit climbs. The older note in this repo calling Dash
"the other rerun-everything rival" was wrong — corrected here. Its server-compute floor
is the same Polars work as everyone else's (100K rows):

| depth | Golit | Marimo | Dash (chain) |
| ---: | ---: | ---: | ---: |
| 1  | 0.09 ms | 0.09 ms | 0.08 ms |
| 3  | 0.12 ms | 0.13 ms | 0.11 ms |
| 10 | 0.27 ms | 0.28 ms | 0.24 ms |

So the floor is a three-way tie dominated by the identical Polars chain — but read the
micro-ordering carefully, because **Dash is not actually faster than Golit.** The Dash
number is measured by calling the callback *function* directly, which bypasses every
part of Dash's per-update work: it is **raw Polars, with no Dash engine in the loop.**
Golit's number is `Session.update` with its whole reactive engine — the PyO3
`dirty_subgraph` call, the epoch-memo signature, registry, and the fragment render +
string-diff. So the ~7 µs gap (120 vs 113 µs at depth 3) is *Golit's entire engine
overhead above bare Polars*, which is about as small as it gets. Measure the work Dash's
`chain()` omits and the picture flips: building the `go.Figure` (~1.02 ms) and
serializing it to the 6.8 KB JSON body (~0.32 ms) make a **real** Dash update ~**1.46 ms**,
roughly **12× Golit's 0.12 ms** — before Flask routing, input deserialization, or
`callback_context`. The floor table is a fair "same Polars work, all three reactive"
read; it is not a claim that Dash is quicker.

The **real** Golit-vs-Dash separation is the wire — and here the benchmark refuted the
pitch I started with, so this is reported straight. Dash's callback returns a Plotly
*figure*, serialized to JSON each interaction and drawn client-side by plotly.js; Golit
renders the *same* chart to a static SVG server-side and ships no charting runtime. For
the same 16-bar chart (uncompressed):

| | per-update payload | one-time client JS |
| --- | ---: | ---: |
| **Golit** (server SVG) | 18.7 KB | ~50 KB (htmx only; **0** charting) |
| **Dash** (figure JSON) | **6.8 KB** | ~5.9 MB (plotly.js 4.84 MB + React + dash-renderer) |

Read that honestly: **per update, Dash is lighter** (6.8 KB < Golit's 18.7 KB SVG) —
"Golit wins bytes/update" is *false*, and the often-quoted Golit "177 B/update" is a
*text* fragment from the synthetic chart, not a real chart, so it isn't the comparison.
Where Golit wins is the **start**: it ships a self-contained SVG and zero charting code,
while Dash front-loads ~5.9 MB of client JS before the first figure draws. Cumulative
bytes `runtime + per_update·N` therefore start far apart and cross only at **≈ 490
interactions** (`b1_dash_crossover.svg`) — Golit ships less *in total* until a session
exceeds several hundred slider moves, and never any charting runtime (the SVG renders
without JS). Dash's trade is the mirror image: a heavy one-time runtime, then light
diffs. (Bytes are uncompressed; gzip shrinks all four numbers, plotly.js most — the
crossover moves but stays in the hundreds.)

The qualitative axis the numbers don't show: Golit infers the dependency DAG from
function signatures; Dash makes you hand-wire every `Input`/`Output`. Same reactive
result, wired by the framework vs wired by you.

```bash
make bench-dash      # Dash floor + bytes + charts (needs the bench group)
# or directly:
uv run --no-sync python -m bench.run_b1_dash   # -> results/b1_dash.csv + b1_dash_bytes.csv
```

Needs the `bench` group: `uv pip install 'dash>=2.14'`.

## B2 — concurrency scaling (`bench/http/run_b2.py`)

B1 is single-client sequential latency; it never asks *how many simultaneous
sessions can one instance hold, and does adding instances help?* That's the
production axis — and the one where Golit's server model should pull ahead of a
single-user notebook kernel, which has no answer here at all. B2 drives the same
real HTTP server as B1 (100K rows, depth 3) with a **closed-loop, multiprocess**
load generator ([`load.py`](http/load.py)): `C` virtual users, each its own
`httpx.AsyncClient` — own cookie jar, hence own Golit **session** — POSTing slider
updates back-to-back over a shared wall-clock window. The users are split across
`min(C, cpu_count)` OS processes so the *driver* never becomes the ceiling (a
single asyncio client tops out near 3000 req/s and would make a faster server look
flat). Two sweeps:

**1. Single-instance saturation** — one server, sweep `C` ∈ {1…64}:

| C | p50 | p99 | throughput |
| ---: | ---: | ---: | ---: |
| 1  | 0.65 ms | 0.90 ms |  1506 req/s |
| 4  | 0.99 ms | 1.27 ms |  3966 req/s |
| 8  | 1.96 ms | 2.38 ms |  **4066 req/s** |
| 16 | 4.00 ms | 5.28 ms |  3958 req/s |
| 32 | 7.98 ms | 8.93 ms |  4004 req/s |
| 64 | 16.4 ms | 21.2 ms |  3866 req/s |

Throughput rises with concurrency to a **~4000 req/s plateau** at C≈8, then holds
flat while latency climbs *linearly* (C=64 p99 is 23× the C=1 floor). That knee is
one core's worth of serial compute: the update handler calls `session.update()`
**inline on the event loop** ([`routes.py`](../python/golit/server/routes.py)), so
I/O overlaps but CPU does not — a single worker is compute-bound, not I/O-bound.
The load curve (`b2_saturation.svg`) hooks up sharply at that throughput.

**2. Horizontal scaling** — fixed saturating load (C=32), add **sticky instances**
`N` ∈ {1,2,4}, each session pinned to one instance by cookie hash (Golit keeps
session state worker-local — no shared store — so this is exactly its scale model):

| N | p50 | p99 | throughput | vs 1 instance |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 7.99 ms | 9.00 ms | 4000 req/s | 1.0× |
| 2 | 5.16 ms | 5.96 ms | 6189 req/s | 1.55× |
| 4 | 4.28 ms | 6.22 ms | 7393 req/s | 1.85× |

Throughput scales with instance count and p99 **recovers** (9.0 → 6.2 ms) even
though total offered load is fixed — sessions spread out, queues drain. The scaling
is **sub-linear**, and the reason is honest and local: this is one 14-core laptop
hosting *both* the N server instances and a 14-process load generator, so at N=4
they contend for the same cores. The scale model is sound (worker-local state, no
cross-instance coordination); demonstrating *clean* linear scaling needs the server
instances on separate hosts from the driver — the cloud step below, not a busier
box. `b2_scaling.svg` plots achieved vs ideal-linear so the gap is visible, not
buried.

```bash
make bench-b2        # full sweep + charts (boots N uvicorns)  (≈1 min)
# or directly:
uv run --no-sync python -m bench.http.run_b2          # -> results/b2.csv
uv run --no-sync python -m bench.http.run_b2 --quick  # fast signal
```

## Still to do (the publishable version)

- All three rivals are now in: Streamlit (rerun-everything) ✅, Marimo (reactive
  notebook) ✅, Dash (manual reactive DAG) ✅. The rerun-everything *slot* has only one
  honest occupant (Streamlit) — Dash turned out reactive, which the benchmark reports
  rather than forcing it into the slot with a strawman single-callback app.
- **B2 across separate hosts** — the scaling sweep is real but capped by running
  servers + driver on one box; put the instances on their own machines to measure
  clean linear scaling. The harness ([`run_b2.py`](http/run_b2.py)) already takes N
  sticky base URLs, so this is a deployment change, not a code one.
- End-to-end numbers over each rival's *real* transport (Streamlit/Marimo websocket,
  Dash's `/_dash-update-component` POST; these comparisons are server-compute only);
  real network RTT; a **standard cloud instance** — everything here is loopback on a
  dev laptop, suggestive not publishable.
