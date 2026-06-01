# Design System Specification: Technical Architect

## 1. Overview & Creative North Star
The Creative North Star for this design system is **"The Blueprint Editorial."** 

In an industry saturated with generic "dark mode" developer tools, this system pivots toward a high-end, sophisticated aesthetic that treats production data with the reverence of a premium architectural journal. We are moving away from the "Dashboard" look and toward a "Document" feel. 

The system leverages **Intentional Asymmetry** and **Node-Link motifs** to represent Directed Acyclic Graph (DAG) architectures. We break the standard grid by allowing technical charts and code blocks to "bleed" into margins or overlap layered surfaces, creating a sense of depth and interconnectedness. This isn't just a tool; it’s a high-fidelity environment for engineering precision.

---

## 2. Colors & Surface Philosophy
We utilize a sophisticated palette that moves beyond flat white. We prioritize tonal depth to guide the eye without the clutter of traditional lines.

### Tone & Surface Guidelines
*   **The "No-Line" Rule:** 1px solid borders are strictly prohibited for sectioning. Boundaries must be defined solely through background shifts (e.g., a `surface-container-low` section sitting on a `surface` background).
*   **Surface Hierarchy & Nesting:** Treat the UI as physical layers. 
    *   **Level 0 (Background):** `surface` (#f7f9fb) or `surface-container-lowest` (#ffffff).
    *   **Level 1 (Main Content):** `surface-container-low` (#f2f4f6).
    *   **Level 2 (Active Modules):** `surface-container` (#eceef0).
*   **The "Glass & Gradient" Rule:** For floating panels or node-details, use Glassmorphism. Apply a `surface-container` color at 80% opacity with a `24px` backdrop-blur. 
*   **Signature Textures:** Main CTAs or active DAG nodes should utilize a subtle linear gradient from `primary` (#004d99) to `primary-container` (#1565c0) at a 135-degree angle to provide a "jewel-toned" depth.

---

## 3. Typography: The Engineering Font Stack
The typography bridges the gap between high-end editorial (Manrope) and technical precision (Inter/JetBrains Mono).

*   **Display & Headlines (Manrope):** Used for high-level data summaries and page titles. The wide apertures of Manrope convey a modern, open feel.
    *   *Role:* Authority and Brand Voice.
*   **UI & Metadata (Inter):** Used for all controls, labels, and body text. Inter is chosen for its exceptional legibility at small sizes (label-sm).
*   **Technical Data (JetBrains Mono/Fira Code):** Every piece of production data, log, or code snippet must use the monospace stack. 
    *   *Rule:* Never mix Inter with raw data. If it’s a variable or a value, it’s Monospace.

| Level | Token | Font | Size | Weight |
| :--- | :--- | :--- | :--- | :--- |
| Display | `display-lg` | Manrope | 3.5rem | 700 |
| Headline | `headline-sm` | Manrope | 1.5rem | 600 |
| Body | `body-md` | Inter | 0.875rem | 400 |
| Code | `label-md` | JetBrains Mono | 0.75rem | 500 |

---

## 4. Elevation & Depth
In this system, elevation is a function of light and tone, not just shadows.

*   **Tonal Layering:** To highlight a code block, do not give it a border. Instead, place the code block on `surface-container-high` (#e6e8ea) against a `surface-container-low` page.
*   **Ambient Shadows:** For "floating" nodes or modals, use a "Cloud Shadow": `0px 12px 32px rgba(25, 28, 30, 0.06)`. This mimics natural light rather than a digital drop-shadow.
*   **The "Ghost Border":** If a technical chart requires containment, use the `outline-variant` (#c2c6d4) at **15% opacity**. It should be felt, not seen.
*   **DAG Motif:** Connect layered cards using "Visual Links"—2px paths using `primary-fixed-dim` (#a9c7ff) that travel between containers to represent data flow.

---

## 5. Components & Interaction

### Data Tables & Technical Charts
*   **Forbid Dividers:** Do not use horizontal lines between rows. Use a 4px vertical gap or a subtle `surface-container-low` hover state to indicate rows.
*   **The Node-Link Chart:** Charts should not sit in a box. They should exist on the `surface`, with axes lines using the `outline-variant` at low opacity.

### Code Blocks
*   **Styling:** Use `surface-container-highest` (#e0e3e5) for the background. 
*   **Interaction:** Include a "Copy" action chip in the top right that only appears on hover. Use `primary-fixed` (#d6e3ff) for syntax highlighting of keywords.

### Reactive Sliders
*   **Track:** Use `surface-container-highest`.
*   **Indicator:** A `primary` (#004d99) gradient pill.
*   **Value:** Always displayed in Monospace above the thumb.

### Buttons & Chips
*   **Primary:** A gradient-fill button with `on-primary` text. No border. Radius: `md` (0.375rem).
*   **Secondary:** `surface-container-high` background with `primary` text.
*   **Chips:** Use `xl` (0.75rem) roundedness. Filter chips should use `outline` for inactive and `primary-container` for active states.

---

## 6. Do’s and Don’ts

### Do:
*   **Do** use asymmetrical margins (e.g., wider left margins for headlines) to create an editorial layout.
*   **Do** use `primary-fixed-dim` for "inactive but connected" DAG nodes.
*   **Do** prioritize white space (spacing tokens 24px, 32px, 48px) over structural lines to separate content.
*   **Do** use Monospace for any value that can be found in a database or config file.

### Don’t:
*   **Don't** use 100% black (#000000). Always use `on-surface` (#191c1e) for text to maintain the premium "ink-on-paper" feel.
*   **Don't** use standard "Material Design" shadows. Keep them large, soft, and barely visible.
*   **Don't** use dividers. If you feel you need a divider, add 16px of extra padding instead.
*   **Don't** use "Alert Red" for everything. Reserve `error` (#ba1a1a) for catastrophic data failure only; use `tertiary` (#813900) for warnings.