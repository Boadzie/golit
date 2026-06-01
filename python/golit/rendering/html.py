"""HTML scaffolding: view slots, out-of-band update fragments, and the page shell.

Styling follows the "Blueprint Editorial" system from ``golit_pages`` — Tailwind
(CDN) with the Material-3 token palette (accent ``primary-container #1565c0``),
Manrope/Inter/JetBrains Mono, and Material Symbols. Components are shadcn-styled
*plain HTML*, server-rendered and swapped by HTMX — no React, no client framework.
"""

from __future__ import annotations

# Pinned client libraries (vendored under client/static in a later pass).
TAILWIND_SRC = "https://cdn.tailwindcss.com?plugins=forms,container-queries"
HTMX_SRC = "https://unpkg.com/htmx.org@2.0.4"
HTMX_SSE_SRC = "https://unpkg.com/htmx-ext-sse@2.2.2"
ALPINE_SRC = "https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js"
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

# Reactive-update flash: HTMX adds .htmx-settling to swapped fragments.
GOLIT_CSS = """
.material-symbols-outlined { font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24; }
.golit-chart svg { max-width: 100%; height: auto; display: block; }
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
<script src="{TAILWIND_SRC}"></script>
<script>{TAILWIND_CONFIG}</script>
<style>{GOLIT_CSS}</style>
<script src="{HTMX_SRC}" defer></script>
<script src="{HTMX_SSE_SRC}" defer></script>
<script src="{ALPINE_SRC}" defer></script>
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
