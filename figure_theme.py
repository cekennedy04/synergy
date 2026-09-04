"""One palette for every matplotlib surface in this project.

Built 2026-09-04. `CLAUDE.md` requires that all colour come from `DESIGN.md`
and that deviations be signed off. `DESIGN.md` covers the tkinter window and
stops there -- it defines one accent, a neutral ramp, and four semantic
confidence tiers, and states plainly:

    **Secondary:** none -- kept restrained; the accent is the only
    non-neutral, non-semantic color in the system.

That is a complete answer for widget chrome and no answer at all for a plot,
which needs to tell a right limb from a left one and six participants from
each other. So every figure-drawing file invented its own palette, and by
2026-09-04 there were four of them:

    clinician_gui.py        DESIGN.md tokens exactly (the only compliant one)
    report_export.py        #1f6fb4 #2e8b57 #4a7c4a #d95f02 #cfe6cf #f2e3c2 ...
    gait_event_picker_ui.py #c1121f #f08c00 #0353a4 #2a9d8f
    session_report.py       four of report_export's, copied rather than shared
    cohort_figures.py       a six-colour categorical set (issue #22)

**The inconsistency was not cosmetic.** The picker drew the right leg warm
(red heel strike, orange toe off) and the left leg cool (blue, teal).
`cohort_figures.py` drew the right side blue and the left side orange. Blue
therefore meant *left* in the window where a clinician picks gait events and
*right* in the figures summarising the cohort those events feed. Nothing
warned about it, because no two of these files shared a line of code.

This module is the fix and the sign-off surface for issue #22: the palette
lives in one place, derives everything it can from `DESIGN.md`, and states the
case for the parts it has to add.

**What is taken unchanged from DESIGN.md.** The neutral ramp and the four
semantic tiers, by value. `cohort_figures.py` had been carrying near-misses of
the same intent (`#fcfcfb` for surface against DESIGN.md's `#FFFFFF`,
`#0b0b0b` for ink against `#1F2421`, `#e1e0d9` for grid against `#D8DBD7`),
which is drift rather than decision, so they are snapped back.

**What is added, and why it is not a deviation of convenience.**

  *Six-way categorical, and everything derived from it.* Taken from
  `cohort_figures.py`, which had already reasoned this out and validated it:
  the `dataviz` reference palette in fixed order, assigned by cohort rank and
  never cycled. One accent cannot become six participants. This is the part
  of issue #22 that genuinely needs a human "yes"; the rest of that issue is
  resolved by derivation rather than by permission.

  *Limb identity.* Slots 1 and 2 of that same palette -- blue and orange --
  which is the widest-separated pair it contains (CVD dE 24.7), and what a
  two-level distinction should spend. This module first proposed a cool
  blue/violet pair instead, on the theory that orange collides with the
  Medium confidence tier the GDI band is painted in. It does not: that band
  is `#FBF0D9`, a near-white amber wash, against which a saturated `#eb6834`
  mark reads as a mark; and the tier's *foreground* amber is `#8A5A00`, a
  dark brown that shares little with it. The violet proposal was also wrong
  for a second and better reason -- see V_ORT below. Limb is nonetheless
  redundantly encoded: `LIMB_STYLE` carries a linestyle and a marker
  alongside the hue, and nothing in this project may distinguish limbs by
  colour alone.

  *Event kind.* Hue is the limb; the marker and a lighter tint are the event.
  A heel strike and a toe off on one leg are therefore the same colour family
  and different shapes, which is the relationship they actually have. The
  previous four unrelated hues encoded no relationship at all.

  *Variance subspaces.* Slots 3 and 7, kept deliberately clear of the two
  that mean right and left everywhere else, because a hue that means "right
  limb" in five figures must not mean "uncontrolled manifold" in the sixth.
  `cohort_figures.py` made that argument and validated the pair (CVD dE 31.1,
  normal 35.8); it is the reason V_ORT is violet and therefore the reason a
  limb cannot be.

**The normative band is semantic, so it uses the semantic tokens.** A GDI
band saying "within one SD of the control mean" / "one to two SD below" is a
confidence statement in the same language as the per-segment tiers, so it is
drawn in High and Medium rather than in a fifth green and a fifth amber
invented for the purpose. That is a derivation from `DESIGN.md`, not an
addition to it.
"""

# -- straight from DESIGN.md -------------------------------------------------

ACCENT = "#0F6B66"
ACCENT_DARK = "#0B4F4B"

BACKGROUND = "#F4F5F3"
SURFACE = "#FFFFFF"
SURFACE_2 = "#F0F1EE"
BORDER = "#D8DBD7"
INK = "#1F2421"
INK_2 = "#5C6560"

# The confidence tiers, light theme. Same values clinician_gui.TIER_COLORS
# uses; DESIGN.md documents them once and both readers derive from it.
TIER = {
    "high":       {"bg": "#E3F3E8", "fg": "#1F6B3B"},
    "medium":     {"bg": "#FBF0D9", "fg": "#8A5A00"},
    "low":        {"bg": "#FBE4E2", "fg": "#A32E24"},
    "not_scored": {"bg": "#ECEDEC", "fg": "#565D5A"},
}

# Figure chrome, derived from the neutral ramp.
GRID = BORDER
BASELINE = INK_2
ZERO_LINE = INK_2

# -- added here, argued for in the module docstring --------------------------

# Six participants. From the dataviz reference palette, in its fixed order;
# assigned by cohort rank and never cycled -- a seventh participant needs the
# palette extended deliberately, not a hue generated on the fly. See issue #22.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")

# Slots 1 and 2: the widest-separated pair the palette contains (CVD dE 24.7).
LIMB = {"right": SERIES[0], "left": SERIES[1]}

# Colour is never the only limb cue -- markers match cohort_figures' own
# SIDE_MARKER so a limb keeps its shape as well as its hue across every
# surface in the project.
LIMB_STYLE = {
    "right": {"color": LIMB["right"], "linestyle": "-",  "marker": "o"},
    "left":  {"color": LIMB["left"],  "linestyle": "--", "marker": "s"},
}

# Lighter tint per limb, for the second of a related pair (toe off against
# heel strike, or a per-stride cloud against its mean).
LIMB_TINT = {"right": "#7fb0e8", "left": "#f5a87e"}

# Hue is the limb, marker and tint are the event kind. Heel strike is the
# darker of the pair because it is the event the segmentation is keyed on.
EVENT_STYLE = {
    "rHS": {"color": LIMB["right"],      "marker": "v",
            "label": "right heel strike"},
    "rTO": {"color": LIMB_TINT["right"], "marker": "^",
            "label": "right toe off"},
    "lHS": {"color": LIMB["left"],       "marker": "v",
            "label": "left heel strike"},
    "lTO": {"color": LIMB_TINT["left"],  "marker": "^",
            "label": "left toe off"},
}

# Background traces an operator picks *against*, rather than reads a value
# off: neutral, so the only colour on the panel is the marks being placed.
#
# These were matplotlib's default cycle until 2026-09-04, which put a C0 blue
# and a C1 orange curve on every panel -- the two hues that now mean right
# limb and left limb. A right-leg panel drawing its toe trace in "left"
# orange is the same confusion the palette was unified to remove, one level
# down. Two tones plus a linestyle tell the two traces apart without
# borrowing a hue that means something.
TRACE = ({"color": INK_2, "linestyle": "-"},
         {"color": "#a8ada9", "linestyle": "--"})

# The GDI normative band, in the semantic tiers rather than in colours
# invented for it. Ordered outermost-first so overlapping spans layer sanely.
NORMATIVE_BAND = (
    {"low": 90.0, "high": 110.0, "color": TIER["high"]["bg"],
     "label": "within 1 SD of control mean"},
    {"low": 80.0, "high": 90.0, "color": TIER["medium"]["bg"],
     "label": "1-2 SD below"},
)
NORMATIVE_MEAN_LINE = TIER["high"]["fg"]

# Variance decomposition. Slots 3 and 7 -- deliberately NOT the limb hues: a
# colour that means "right limb" in five figures must not mean "uncontrolled
# manifold" in the sixth. Validated as a pair (CVD dE 31.1, normal 35.8).
V_UCM = SERIES[2]
V_ORT = "#4a3aa7"


def series_color(index):
    """The categorical colour for series `index`, wrapping past six."""
    return SERIES[index % len(SERIES)]


def limb_style(side, **overrides):
    """Colour + linestyle + marker for a limb, ready to splat into a plot call.

    `side` accepts 'right'/'left' or the single-letter 'r'/'l' the gait code
    uses internally, because both spellings are live in this repo and a
    KeyError on the short one would be a needless trap.
    """
    key = {"r": "right", "l": "left"}.get(side, side)
    if key not in LIMB_STYLE:
        raise ValueError(
            f"unknown limb {side!r}; expected 'right'/'left' (or 'r'/'l').")
    style = dict(LIMB_STYLE[key])
    style.update(overrides)
    return style


def style_axis(axis, grid_axis="both"):
    """The shared plot chrome: muted grid, neutral spines, secondary-ink ticks.

    Applied by every figure in the project so a curve exported to PDF and the
    same curve in the cohort report do not sit on two different-looking axes.
    """
    axis.grid(True, axis=grid_axis, color=GRID, alpha=0.9, linewidth=0.8)
    axis.set_axisbelow(True)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color(BORDER)
    axis.tick_params(colors=INK_2, labelcolor=INK)
    return axis
