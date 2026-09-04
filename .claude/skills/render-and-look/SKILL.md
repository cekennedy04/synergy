---
name: render-and-look
description: Use after changing anything that draws a figure, a PDF page, or the gait-event picker - render_gallery.py writes every clinician-facing surface to PNG so they can be looked at. A green test suite does not mean the output is readable.
---

# Render and look

## Why this exists

Three defects shipped past a fully green test suite in this repo. All three
were obvious within about two seconds of opening the picture, and none of them
was reachable by an assertion anyone would have thought to write:

- The GDI legend sat in the lower right. On a GDI axis, low means impaired --
  so the legend was covering the strides of the worst limb in the trial, the
  one the report was opened to look at. Every assertion passed. The data was
  in the artist, just underneath a white box.
- The GDI basis line ran off the right edge of the page, taking with it the
  sentence saying the score covers the whole session rather than this trial.
  `wrap=True` measures against the figure, not the axes.
- The gait-event picker drew its background traces in matplotlib's default
  cycle, so a C1 orange curve appeared on the *right* leg's panel -- orange
  being the colour that means "left limb" everywhere else in the project.

The pattern: **tests verify that a value reached an artist. They do not verify
that a human can read it.** Occlusion, clipping, overflow, contrast and colour
collision all live in the gap between those two things.

## The command

```
~/miniconda3/python.exe render_gallery.py --open
```

Base python. No opensim, no display, no tkinter. Writes ten PNGs to
`context/render-gallery/` (gitignored) and opens the folder.

Then **actually open them**. The step that gets skipped is not the rendering.

## When

Before landing any change to: `report_export.py`, `session_report.py`,
`figure_theme.py`, `gait_event_picker_ui.py`, `cohort_figures.py`, or
`clinician_gui.build_curve_figure`. Also after any change to `figure_theme.py`
tokens, because that file reaches all of them at once.

## What to look for

Work down this list against each PNG. It is ordered by how often each one has
actually bitten.

1. **Is anything covering anything?** Legends and annotations are the usual
   culprits. Ask where the *bad* data lands on this axis, not where the data
   in your fixture landed -- a legend that is clear for a healthy trial can
   sit exactly on an impaired one.
2. **Does any text touch or cross a margin?** Especially anything built by
   string concatenation, which grows over time without anyone re-checking the
   width. Use `report_export._wrapped_note`, not matplotlib's `wrap=True` --
   `wrap` measures against the figure, so a text placed at `x=0.05` in axes
   coordinates gets a left margin and no right one.
3. **Does any text overflow its container?** Table cells clip and then spill
   into the neighbouring column, which reads as data belonging to the wrong
   column rather than as a rendering fault.
4. **Does a colour mean the same thing it means everywhere else?** Right is
   blue, left is orange, and the subspace colours are neither. All of it comes
   from `figure_theme.py`; a literal hex in a drawing file is the bug.
5. **Is limb distinguishable without colour?** Linestyle and marker must carry
   it too. Check by imagining the page in greyscale.
6. **Does the legend describe the whole figure?** A key built from
   "whichever series was plotted first" is a statement about that series
   wearing a label that claims to explain all of them.
7. **Is a semantic tier actually shown as its tier?** DESIGN.md defines
   High/Medium/Low/Not scored colours. A page that renders them as identical
   black text has thrown away the one thing tiers are for.
8. **Does an empty or partial case still say something?** A section that
   silently disappears when its data is missing produces a report
   indistinguishable from one where everything was fine.

## The fixtures are the valuable part

`render_gallery.py`'s fixtures are deliberately awkward, and that is what
makes the gallery worth anything. A gallery rendered from tidy symmetric data
shows nothing:

- the legend collision only appeared because one limb was impaired and its
  strides sat low on the axis;
- the truncation only appeared because the basis string had grown long enough
  to reach the margin;
- the picker's legend problem only appears when the walking sits at one end of
  the trial, which is what a real capture looks like after a standing start.

So the fixtures carry an impaired limb, a long note, a missing leg, an
unavailable section, and a trial with a flat lead-in.

**When a case renders badly in the wild, add it to `render_gallery.py` rather
than only fixing it in place.** The gallery is this project's regression
record for the things tests cannot hold.

## Not covered

`cohort_figures.py`'s six figures need a scored cohort, and `session_report.py`'s
pages need a pooled session -- both live behind real data under `context/`.
Render those by running their own CLIs when you touch them.
