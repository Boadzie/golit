"""HTML scaffolding: view slots, out-of-band update fragments, and the page shell.

The page shell loads HTMX (+ SSE extension) and Alpine, and a small "Blueprint
Editorial" stylesheet (accent ``#1565C0``, tonal surfaces, soft shadows, no hard
dividers) matching the design system in ``golit_pages/golit_logic/DESIGN.md``.
"""

from __future__ import annotations

# Pinned client libraries (vendored under client/static in a later pass).
HTMX_SRC = "https://unpkg.com/htmx.org@2.0.4"
HTMX_SSE_SRC = "https://unpkg.com/htmx-ext-sse@2.2.2"
ALPINE_SRC = "https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js"
FONTS_HREF = (
    "https://fonts.googleapis.com/css2?family=Manrope:wght@600;700&"
    "family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap"
)


def view_slot(node_id: str, content: str) -> str:
    """A view's place in the initial layout (also the SSE swap target)."""
    return (
        f'<div id="{node_id}" class="golit-view" hx-ext="sse" '
        f'sse-swap="node:{node_id}">{content}</div>'
    )


def oob_fragment(node_id: str, content: str) -> str:
    """An out-of-band swap fragment for a POST response: HTMX places it by id
    regardless of the triggering element's target."""
    return f'<div id="{node_id}" class="golit-view" hx-swap-oob="true">{content}</div>'


def page(title: str, body: str) -> str:
    """Wrap rendered body markup in the full HTML document shell."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS_HREF}">
<style>{BLUEPRINT_CSS}</style>
<script src="{HTMX_SRC}" defer></script>
<script src="{HTMX_SSE_SRC}" defer></script>
<script src="{ALPINE_SRC}" defer></script>
</head>
<body hx-ext="sse">
<main class="golit-app">
<header class="golit-header"><h1>{title}</h1></header>
{body}
</main>
</body>
</html>"""


BLUEPRINT_CSS = """
:root {
  --surface: #f7f9fb; --surface-lowest: #ffffff; --surface-low: #f2f4f6;
  --surface-container: #eceef0; --surface-high: #e6e8ea; --surface-highest: #e0e3e5;
  --on-surface: #191c1e; --on-surface-variant: #41484d;
  --primary: #004d99; --primary-container: #1565c0; --primary-fixed-dim: #a9c7ff;
  --outline-variant: #c2c6d4; --error: #ba1a1a;
  --radius-md: 0.375rem; --radius-xl: 0.75rem;
  --shadow-cloud: 0 12px 32px rgba(25,28,30,0.06);
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--surface); color: var(--on-surface);
  font-family: Inter, system-ui, sans-serif; font-size: 0.875rem; line-height: 1.6;
}
.golit-app { max-width: 1100px; margin: 0 auto; padding: 48px 32px 96px; }
.golit-header h1 {
  font-family: Manrope, sans-serif; font-weight: 700; font-size: 2.25rem;
  margin: 0 0 32px; letter-spacing: -0.02em; padding-left: 8px;
}
.golit-view { margin: 24px 0; }
.golit-chart {
  background: var(--surface-lowest); border-radius: var(--radius-md);
  padding: 16px; box-shadow: var(--shadow-cloud); overflow: auto;
}
.golit-chart svg { max-width: 100%; height: auto; display: block; }
.golit-value {
  font-family: "JetBrains Mono", monospace; font-size: 0.75rem; font-weight: 500;
  background: var(--surface-highest); color: var(--on-surface);
  padding: 12px 16px; border-radius: var(--radius-md); margin: 0;
}
.golit-widget { margin: 16px 0; display: flex; flex-direction: column; gap: 6px; }
.golit-label {
  font-size: 0.75rem; font-weight: 600; color: var(--on-surface-variant);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.golit-widget output {
  font-family: "JetBrains Mono", monospace; font-size: 0.875rem; color: var(--primary);
}
.golit-slider input[type=range] { accent-color: var(--primary-container); width: 100%; }
.golit-widget input[type=text], .golit-widget input[type=number],
.golit-widget select, .golit-widget input[type=file] {
  background: var(--surface-highest); border: none; border-radius: var(--radius-md);
  padding: 8px 12px; font-family: inherit; font-size: 0.875rem; color: var(--on-surface);
}
.golit-table { border-collapse: separate; border-spacing: 0 4px; width: 100%; }
.golit-table th {
  text-align: left; font-size: 0.7rem; text-transform: uppercase;
  letter-spacing: 0.04em; color: var(--on-surface-variant); padding: 4px 12px;
}
.golit-table td {
  font-family: "JetBrains Mono", monospace; font-size: 0.75rem;
  padding: 6px 12px; background: var(--surface-low);
}
.golit-table tr:hover td { background: var(--surface-container); }
.golit-table-more {
  caption-side: bottom; font-size: 0.7rem; color: var(--on-surface-variant);
  text-align: right; padding-top: 8px;
}
"""
