"""HTML scaffolding: view slots, out-of-band update fragments, and the page shell.

Styling follows the "Blueprint Editorial" system from ``golit_pages`` — Tailwind
(CDN) with the Material-3 token palette (accent ``primary-container #1565c0``),
Manrope/Inter/JetBrains Mono, and Material Symbols. Components are shadcn-styled
*plain HTML*, server-rendered and swapped by HTMX — no React, no client framework.
"""

from __future__ import annotations

import json

# Pinned client libraries (vendored under client/static in a later pass).
TAILWIND_SRC = "https://cdn.tailwindcss.com?plugins=forms,container-queries"
HTMX_SRC = "https://unpkg.com/htmx.org@2.0.4"
HTMX_SSE_SRC = "https://unpkg.com/htmx-ext-sse@2.2.2"
HTMX_WS_SRC = "https://unpkg.com/htmx-ext-ws@2.0.3"
ALPINE_SRC = "https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js"

# CDN runtimes for interactive charts, loaded lazily by the bootstrap below —
# only when an app actually emits a mount for that library. Bokeh is special:
# its JS must match the installed Python Bokeh, so the version rides on the mount
# (data-chart-version) and the loader builds the URLs from this base.
CHART_CDN = {
    "plotly": ["https://cdn.plot.ly/plotly-2.35.2.min.js"],
    "vega": [
        "https://cdn.jsdelivr.net/npm/vega@5",
        "https://cdn.jsdelivr.net/npm/vega-lite@5",
        "https://cdn.jsdelivr.net/npm/vega-embed@6",
    ],
    "anychart": ["https://cdn.anychart.com/releases/8.13.0/js/anychart-bundle.min.js"],
    # MapLibre GL JS — native, GPU vector maps (golit.gis). Its stylesheet is a
    # hard requirement, linked unconditionally in the shell head (see MAPLIBRE_CSS).
    "maplibre": ["https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js"],
}
BOKEH_CDN_BASE = "https://cdn.bokeh.org/bokeh/release/bokeh"
BOKEH_DEFAULT_VERSION = "3.6.0"
# MapLibre needs its CSS for controls/canvas positioning; unlike the chart runtimes
# (lazy-loaded by the bootstrap) a stylesheet must be in <head>, so it is linked
# there always. It's small and cached; the JS still loads lazily only when a map mounts.
MAPLIBRE_CSS = "https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css"
FONTS_HREF = (
    "https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&"
    "family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap"
)
SYMBOLS_HREF = (
    "https://fonts.googleapis.com/css2?"
    "family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
)

# Material-3 token palette lifted verbatim from golit_pages so apps can use the
# same Tailwind color/utility names as the design mockups.
TAILWIND_CONFIG = """
tailwind.config = {
  theme: { extend: {
    colors: {
      "primary": "#004d99", "on-primary": "#ffffff",
      "primary-container": "#1565c0", "on-primary-container": "#dae5ff",
      "primary-fixed": "#d6e3ff", "primary-fixed-dim": "#a9c7ff",
      "secondary": "#4a5f83", "secondary-container": "#c0d5ff",
      "tertiary": "#813900", "tertiary-container": "#a64c00",
      "error": "#ba1a1a", "error-container": "#ffdad6", "on-error": "#ffffff",
      "background": "#f7f9fb", "on-background": "#191c1e",
      "surface": "#f7f9fb", "on-surface": "#191c1e", "on-surface-variant": "#424752",
      "surface-container-lowest": "#ffffff", "surface-container-low": "#f2f4f6",
      "surface-container": "#eceef0", "surface-container-high": "#e6e8ea",
      "surface-container-highest": "#e0e3e5", "surface-variant": "#e0e3e5",
      "outline": "#727783", "outline-variant": "#c2c6d4"
    },
    borderRadius: { DEFAULT: "0.125rem", lg: "0.25rem", xl: "0.5rem", full: "0.75rem" },
    fontFamily: {
      headline: ["Manrope"], body: ["Inter"], label: ["Inter"], mono: ["JetBrains Mono"]
    },
    fontSize: {
      "display-lg": ["3.5rem", { fontWeight: "700" }],
      "headline-sm": ["1.5rem", { fontWeight: "600" }],
      "body-md": ["0.875rem"], "label-md": ["0.75rem", { fontWeight: "500" }]
    }
  } }
}
"""

# Hydrates `.golit-chart` mounts (see rendering/interactive.py): lazy-loads each
# library's CDN runtime once, then draws the JSON spec. Registered via htmx.onLoad
# so it runs on the initial render AND after every POST/OOB/SSE swap, and guarded
# by data-chart-rendered so re-firing is idempotent.
CHART_BOOTSTRAP = """
(function () {
  var _loading = {};
  function loadOne(src) {
    if (_loading[src]) return _loading[src];
    _loading[src] = new Promise(function (res, rej) {
      var s = document.createElement('script');
      s.src = src; s.async = false; s.crossOrigin = 'anonymous';
      s.onload = function () { res(); };
      s.onerror = function () { rej(new Error('golit: failed to load ' + src)); };
      document.head.appendChild(s);
    });
    return _loading[src];
  }
  function loadSeq(urls) {
    return urls.reduce(function (p, u) {
      return p.then(function () { return loadOne(u); });
    }, Promise.resolve());
  }
  function ensure(lib, version) {
    var cdn = window.GOLIT_CHART_CDN || {};
    if (lib === 'plotly') return window.Plotly ? Promise.resolve() : loadSeq(cdn.plotly || []);
    if (lib === 'vega') return window.vegaEmbed ? Promise.resolve() : loadSeq(cdn.vega || []);
    if (lib === 'anychart') {
      return window.anychart ? Promise.resolve() : loadSeq(cdn.anychart || []);
    }
    if (lib === 'maplibre') {
      return window.maplibregl ? Promise.resolve() : loadSeq(cdn.maplibre || []);
    }
    if (lib === 'bokeh') {
      if (window.Bokeh && window.Bokeh.embed) return Promise.resolve();
      var v = version || window.GOLIT_BOKEH_VERSION, b = window.GOLIT_BOKEH_BASE;
      return loadSeq([b + '-' + v + '.min.js', b + '-widgets-' + v + '.min.js',
                      b + '-tables-' + v + '.min.js']);
    }
    return Promise.reject(new Error('golit: unknown chart lib ' + lib));
  }
  function drawAnyChart(el, spec) {
    var kind = spec.kind || 'column', chart;
    if (kind === 'pie' || kind === 'donut' || kind === 'funnel') {
      chart = anychart[kind](spec.data);
    } else { chart = anychart[kind](); chart[kind](spec.data); }
    if (spec.title) chart.title(spec.title);
    chart.container(el); chart.draw();
  }
  function drawMap(el, spec) {
    // A maplibre spec carries a full style (URL or dict) plus camera. geo_map's
    // GeoJSON source + layers live inside `style`, so the map is fully declarative
    // and redraws identically on a swap — each swap is a fresh element, and the old
    // map's WebGL context is freed by the htmx:beforeCleanupElement hook below.
    if (el.style && spec.height) el.style.height = spec.height;
    var opts = {container: el, style: spec.style};
    if (spec.bounds) { opts.bounds = spec.bounds; opts.fitBoundsOptions = {padding: 24}; }
    else {
      opts.center = spec.center || [0, 0];
      opts.zoom = (spec.zoom != null) ? spec.zoom : 1;
    }
    if (spec.pitch) opts.pitch = spec.pitch;
    if (spec.bearing) opts.bearing = spec.bearing;
    if (spec.minZoom != null) opts.minZoom = spec.minZoom;
    if (spec.maxZoom != null) opts.maxZoom = spec.maxZoom;
    var map = new maplibregl.Map(opts);
    el._golitMap = map;
    // geo_map can request click popups over its data layer: spec.tooltip lists the
    // feature properties to show, spec.tooltipLayer is the layer to bind. Values are
    // escaped — the GeoDataFrame is developer data, but treat it as untrusted anyway.
    if (spec.tooltip && spec.tooltipLayer) {
      var esc = function (s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
          return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
        });
      };
      var fields = spec.tooltip, layer = spec.tooltipLayer;
      var popup = new maplibregl.Popup({closeButton: false});
      map.on('click', layer, function (e) {
        var f = e.features && e.features[0];
        if (!f) return;
        var rows = fields.map(function (k) {
          return '<div><span style="color:#727783">' + esc(k) + '</span> ' +
                 esc(f.properties[k]) + '</div>';
        }).join('');
        popup.setLngLat(e.lngLat).setHTML('<div style="font:12px Inter,sans-serif">' +
          rows + '</div>').addTo(map);
      });
      map.on('mouseenter', layer, function () { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', layer, function () { map.getCanvas().style.cursor = ''; });
    }
  }
  function draw(el, lib, spec) {
    if (lib === 'plotly') {
      Plotly.newPlot(el, spec.data || [], spec.layout || {},
                     {responsive: true, displaylogo: false});
    } else if (lib === 'vega') {
      vegaEmbed(el, spec, {actions: false});
    } else if (lib === 'bokeh') {
      if (!el.id) el.id = 'golit-bk-' + Math.random().toString(36).slice(2);
      Bokeh.embed.embed_item(spec, el.id);
    } else if (lib === 'anychart') {
      drawAnyChart(el, spec);
    } else if (lib === 'maplibre') {
      drawMap(el, spec);
    }
  }
  // A swap replaces a view's <section>, detaching any map it held. A MapLibre map
  // owns a WebGL context (browsers cap how many can be live), so free it explicitly
  // when htmx cleans up the element rather than leaking the context on every update.
  function disposeMaps(node) {
    if (node && node._golitMap) {
      try { node._golitMap.remove(); } catch (e) {}
      node._golitMap = null;
    }
    if (node && node.querySelectorAll) {
      Array.prototype.forEach.call(node.querySelectorAll('.golit-chart'), function (el) {
        if (el._golitMap) { try { el._golitMap.remove(); } catch (e) {} el._golitMap = null; }
      });
    }
  }
  function initCharts(root) {
    root = root || document;
    if (!root.querySelectorAll) return;
    var mounts = root.querySelectorAll('.golit-chart[data-chart-lib]');
    Array.prototype.forEach.call(mounts, function (el) {
      if (el.getAttribute('data-chart-rendered')) return;
      var lib = el.getAttribute('data-chart-lib'), raw = el.getAttribute('data-chart-spec');
      if (!raw) return;
      var spec;
      try { spec = JSON.parse(raw); }
      catch (e) { console.error('golit: bad chart spec', e); return; }
      el.setAttribute('data-chart-rendered', '1');
      ensure(lib, el.getAttribute('data-chart-version'))
        .then(function () { draw(el, lib, spec); })
        .catch(function (e) { console.error(e); el.removeAttribute('data-chart-rendered'); });
    });
  }
  window.golitInitCharts = initCharts;
  function start() {
    // Re-init on every swap, OOB included. A plain htmx:load listener (not the
    // htmx.onLoad helper) so registration can't lose a race with htmx's own deferred
    // <script>: if window.htmx isn't defined yet when start() runs, the guarded
    // onLoad call silently no-ops and swapped-in charts/maps never hydrate.
    document.addEventListener('htmx:load', function (e) {
      initCharts((e.detail && e.detail.elt) || e.target);
    });
    // htmx fires this per element it removes during a swap (POST/OOB and SSE alike).
    document.addEventListener('htmx:beforeCleanupElement', function (e) {
      disposeMaps(e.target);
    });
    initCharts(document);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
"""

# Keeps each chat log (golit.ui.chat) pinned to the newest message. Messages arrive
# as out-of-band appends over the ws extension, so we watch the log for child changes
# and scroll to the bottom. Registered via htmx.onLoad → also works after swaps.
CHAT_BOOTSTRAP = """
(function () {
  function attach(root) {
    root = root || document;
    if (!root.querySelectorAll) return;
    Array.prototype.forEach.call(root.querySelectorAll('.golit-chat-log'), function (el) {
      if (el.__golitChat) return;
      el.__golitChat = true;
      var pin = function () { el.scrollTop = el.scrollHeight; };
      new MutationObserver(pin).observe(el, { childList: true });
      pin();
    });
  }
  function start() {
    // Plain htmx:load listener (not htmx.onLoad) so it can't lose a race with htmx's
    // deferred <script> — see the chart bootstrap for the same fix.
    document.addEventListener('htmx:load', function (e) {
      attach((e.detail && e.detail.elt) || e.target);
    });
    attach(document);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
"""

# Reactive-update flash: HTMX adds .htmx-settling to swapped fragments.
GOLIT_CSS = """
.material-symbols-outlined { font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24; }
.golit-chart svg { max-width: 100%; height: auto; display: block; }
[x-cloak] { display: none !important; }
.golit-expander summary::-webkit-details-marker { display: none; }
.golit-expander summary { list-style: none; }
.golit-chev { transition: transform .2s ease; }
.golit-expander[open] .golit-chev { transform: rotate(180deg); }
.golit-view.htmx-settling { animation: golit-flash .7s ease-out; }
@keyframes golit-flash {
  from { box-shadow: 0 0 0 2px #004d99 inset; }
  to   { box-shadow: 0 0 0 0 transparent inset; }
}
"""


def view_slot(node_id: str, content: str, *, oob: bool = False) -> str:
    """A view's card in the layout and its SSE swap target. With ``oob`` it
    carries ``hx-swap-oob`` so a POST response swaps it by id."""
    oob_attr = ' hx-swap-oob="true"' if oob else ""
    return (
        f'<section id="{node_id}" class="golit-view bg-surface-container-low rounded-xl '
        f'p-6 transition-all" sse-swap="node:{node_id}"{oob_attr}>{content}</section>'
    )


def oob_fragment(node_id: str, content: str) -> str:
    """An out-of-band swap fragment for a POST response."""
    return view_slot(node_id, content, oob=True)


def controls_panel(controls: list[str]) -> str:
    """Group input controls into a card above the views."""
    if not controls:
        return ""
    inner = "".join(controls)
    return (
        '<aside class="golit-controls bg-surface-container-low rounded-xl p-6 mb-8 '
        f'grid gap-6 sm:grid-cols-2 lg:grid-cols-3">{inner}</aside>'
    )


def page(title: str, body: str) -> str:
    """Wrap rendered body markup in the full HTML document shell."""
    chart_cdn = (
        f"window.GOLIT_CHART_CDN={json.dumps(CHART_CDN)};"
        f"window.GOLIT_BOKEH_BASE={json.dumps(BOKEH_CDN_BASE)};"
        f"window.GOLIT_BOKEH_VERSION={json.dumps(BOKEH_DEFAULT_VERSION)};"
    )
    return f"""<!doctype html>
<html lang="en" class="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS_HREF}">
<link rel="stylesheet" href="{SYMBOLS_HREF}">
<link rel="stylesheet" href="{MAPLIBRE_CSS}">
<script src="{TAILWIND_SRC}"></script>
<script>{TAILWIND_CONFIG}</script>
<style>{GOLIT_CSS}</style>
<script src="{HTMX_SRC}" defer></script>
<script src="{HTMX_SSE_SRC}" defer></script>
<script src="{HTMX_WS_SRC}" defer></script>
<script src="{ALPINE_SRC}" defer></script>
<script>{chart_cdn}</script>
<script>{CHART_BOOTSTRAP}</script>
<script>{CHAT_BOOTSTRAP}</script>
</head>
<body class="bg-surface text-on-surface font-body antialiased" hx-ext="sse" sse-connect="/events">
<div class="max-w-6xl mx-auto px-6 py-10">
<header class="mb-8 flex items-baseline justify-between">
<div>
<h1 class="font-headline text-3xl font-extrabold tracking-tighter">{title}</h1>
<p class="text-[10px] uppercase tracking-widest text-on-surface-variant mt-1">Powered by Golit</p>
</div>
<span class="font-mono text-[10px] text-outline uppercase tracking-widest">reactive · htmx</span>
</header>
<main>
{body}
</main>
</div>
</body>
</html>"""
