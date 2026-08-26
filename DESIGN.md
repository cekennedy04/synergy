# Design System — Synergy Clinician Trial Report

## Product Context
- **What this is:** A tkinter/ttk desktop tool (`clinician_gui.py`) that runs the Xsens→OpenSim gait pipeline on a session/trial, shows metadata, joint-angle curves, gait metrics, and per-segment confidence indicators, and exports a one-click PDF report.
- **Who it's for:** A clinician or researcher on the Synergy project, running trials repeatedly and scanning results quickly — not a general consumer audience.
- **Space/industry:** Clinical gait analysis / biomechanics research tooling. Category peers: Vicon Nexus, Qualisys QTM/QGait, and scientific instrument software generally (OpenSim's own GUI, REDCap, PACS viewers).
- **Project type:** Native desktop application (tkinter), single-window, task-focused, run repeatedly per session.

## Aesthetic Direction
- **Direction:** Industrial/Utilitarian — function-first, data-dense, muted palette.
- **Decoration level:** Minimal — no ornament; hierarchy comes from spacing, weight, and confidence-tier color coding.
- **Mood:** Should feel like a lab instrument readout, not a marketing product — quiet, precise, built for a clinician's eye to land on the number that needs scrutiny in seconds, not minutes.
- **Reference sites:** Vicon Nexus (vicon.com/software/nexus) marketing page reviewed for category context; explicitly discounted as a UI signal — it's lead-gen copywriting (dark navy, orange CTAs, athlete photography), not representative of the actual in-app software experience. The real reference class is scientific/clinical desktop tooling generally (Qualisys QTM/QGait, OpenSim GUI, REDCap, PACS viewers): dense multi-panel layouts, muted palettes, tabular numerals, semantic-only color.

## Typography
- **Display/Hero:** Times New Roman — section headers and screen titles. User-requested override from an initial Segoe UI proposal; reads more "clinical report" than "instrument panel," a deliberate departure from the utilitarian direction, kept because it's the explicit choice.
- **Body:** Times New Roman — labels, descriptions, running text.
- **UI/Labels:** Times New Roman, uppercase with slight letter-spacing for eyebrow/caption text (session ID, tier names).
- **Data/Tables:** Cascadia Code (fallback: Consolas, then JetBrains Mono) — all numeric data throughout the app, not just tables. Must render with `font-variant-numeric: tabular-nums` (or the tkinter/ttk equivalent — a genuinely fixed-width font, since ttk has no tabular-nums feature) so joint angles, timestamps, and metric values align in columns.
- **Loading:** Times New Roman and Consolas/Cascadia Code are standard Windows-installed fonts — no font install or bundling needed for this desktop target. If this ever ships on macOS/Linux, verify Cascadia Code is present or fall back to Consolas/JetBrains Mono/monospace.
- **Scale:** Screen title 20-22px semibold-weight equivalent; section header 12-13px uppercase, letter-spacing ~0.06em; body/labels 13-14px; data values 13-15px monospace.

## Color
- **Approach:** Balanced — one muted accent + neutrals, with semantic colors carrying all status meaning.
- **Primary (accent):** `#0F6B66` (deep muted teal) — buttons, links, active states. Hover/pressed shade: `#0B4F4B`. Dark mode: `#3FB6AE`. Deliberate departure from the generic clinical blue used by most EMR/clinical software; makes the tool visually distinct without breaking category conventions.
- **Secondary:** none — kept restrained; the accent is the only non-neutral, non-semantic color in the system.
- **Neutrals:** Warm-tinted grays, not pure gray. Light: background `#F4F5F3`, surface `#FFFFFF`, surface-2 `#F0F1EE`, border `#D8DBD7`, text `#1F2421`, text-secondary `#5C6560`. Dark: background `#14181A`, surface `#1C2225`, surface-2 `#202729`, border `#2C3438`, text `#E7ECEA`, text-secondary `#9AA6A1`.
- **Semantic (confidence tiers — matches existing `TIER_COLORS` in `clinician_gui.py`):**
  - High: bg `#E3F3E8` / fg `#1F6B3B` (dark: bg `#163826` / fg `#6FDB9B`)
  - Medium: bg `#FBF0D9` / fg `#8A5A00` (dark: bg `#3A2E0C` / fg `#E8C15C`)
  - Low: bg `#FBE4E2` / fg `#A32E24` (dark: bg `#3A1815` / fg `#F19188`)
  - Not scored: bg `#ECEDEC` / fg `#565D5A` (dark: bg `#262C2E` / fg `#A7B0AD`)
  - These are the traffic-light convention clinicians already expect — kept as a safe choice, not reinterpreted.
- **Dark mode:** Full token swap (not a simple invert) — see neutrals/semantic values above. Accent brightens for contrast against the dark ground; tier backgrounds darken while foregrounds lighten to hold WCAG-legible contrast.

## Spacing
- **Base unit:** 8px.
- **Density:** Compact — this is a data tool where screen space goes to curves and tables, not whitespace.
- **Scale:** 2xs(4) sm(8) md(12) lg(16) xl(24) 2xl(32) 3xl(48)

## Layout
- **Approach:** Grid-disciplined — matches tkinter's own grid geometry manager and the existing `ttk.LabelFrame` sectioning in `clinician_gui.py`. Predictable panel placement (metadata panel left, curves/metrics/export right) so a clinician builds muscle memory across repeated sessions.
- **Grid:** Fixed two-column layout at desktop width (metadata sidebar ~260px + flexible main content); stacks to single column below ~720px if the window is resized narrow.
- **Max content width:** Not applicable to the native window (no page width to cap); panels themselves cap at comfortable reading/data widths within their LabelFrame.
- **Border radius:** sm 3px (chips/tags), md 5px (panels, buttons), lg 8px (outer window/card) — small and utilitarian, not the bubbly rounded-everything look.

## Motion
- **Approach:** Minimal-functional — tkinter has no native animation system and this is a data tool, not a marketing surface. Motion exists only where it aids comprehension.
- **Easing:** Not applicable to tkinter widgets directly; if any custom transition is built (e.g. a progress indicator), ease-out on appear, ease-in on dismiss.
- **Duration:** Micro (50-100ms) for any hover/pressed state feedback; short (150-250ms) for the PDF-export progress indicator; nothing longer — this app should never feel like it's making the user wait on decoration.

## Component Notes (from the approved preview)
- Buttons: primary (solid teal, white text), secondary (bordered, neutral), ghost (text-only, teal) — see preview mockup for exact treatment.
- Confidence tier chips: small, monospace, tier-colored background/foreground pair from the semantic table above. In the clinician GUI's actual joint-curve panels, the chip text is the full accessibility-required sentence ("High agreement with the suit's own onboard estimate...", not a short "HIGH" tag) per the product plan's KTD5 — that sentence stays sentence-case rather than uppercase, since all-caps long-form text is a readability regression the short-tag preview mockup didn't need to account for. A short standalone tag (as in the design-system preview) would use uppercase.
- Gait metrics table: metric name left-aligned (body font), value right-aligned (data font, tabular), confidence tier as a chip in a third column.
- Session metadata panel: label/value rows, label in text-secondary, value in data font — applied to every value in the row (not just numeric ones), matching the approved preview, which rendered the session ID and trial name in the data font alongside the numeric fields for a consistent "readout" column.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-21 | Initial design system created | Created by /design-consultation. Researched category (Vicon Nexus marketing discounted as non-representative; scientific/clinical desktop tooling used as the real reference class). Proposed industrial-utilitarian direction with a teal accent and monospace data typography as deliberate risks; user approved as-is. |
| 2026-08-21 | Display/body font changed to Times New Roman | User-requested override of the initial Segoe UI proposal. Data/tables font (Cascadia Code/Consolas) left unchanged since it serves a distinct alignment role. |
| 2026-08-21 | Design system applied to `clinician_gui.py`, reviewed (correctness/project-standards/testing/adversarial), fixes applied | Colors, fonts, spacing, button hierarchy, section-header casing, and metrics-table alignment wired in via `ttk.Style`. Two DESIGN.md tokens (accent hover shade, chip text casing for this app's actual accessibility-required sentence-length labels) were under-specified and corrected here to match what was actually built/approved, not the other way around. Two DESIGN.md items are **not implemented and disclosed, not silently dropped**: dark mode (tkinter/ttk has no reliable OS dark-mode hook the way a browser does) and border-radius (`ttk`'s stock themes have no radius primitive; would require custom-drawn widgets disproportionate to this app's scope) — both flagged to the user rather than assumed acceptable. |
