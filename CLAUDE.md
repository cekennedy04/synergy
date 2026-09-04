## Design System
Always read DESIGN.md before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.

## Render and look
Figures and PDF pages are not finished when the tests pass. Before landing a
change to anything that draws (`report_export.py`, `session_report.py`,
`figure_theme.py`, `gait_event_picker_ui.py`, `cohort_figures.py`,
`clinician_gui.build_curve_figure`), run:

```
~/miniconda3/python.exe render_gallery.py --open
```

and look at the output. Tests verify a value reached an artist; they do not
verify a human can read it. Occlusion, clipping, margin overrun and colour
collision all live in that gap, and three of them shipped past a green suite
here. The checklist of what to look for, and why the fixtures are deliberately
awkward, is in `.claude/skills/render-and-look/SKILL.md`.
