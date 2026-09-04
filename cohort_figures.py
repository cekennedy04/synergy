"""Render the cohort report's figures from `cohort_scores.py`'s JSON.

Built 2026-09-02. Split from the scoring pass on purpose: a figure can be
restyled without reloading six OpenSim models, and the numbers a figure draws
are a file on disk that can be diffed between runs rather than a value that only
ever existed inside one process.

**Colour.** `DESIGN.md` governs the clinician GUI and fixes a single teal accent
with semantic status colours. That system cannot carry six participant series --
one accent is one series, and the status colours are reserved. So identity here
comes from the validated categorical palette in the `dataviz` reference
(`#2a78d6 #eb6834 #1baf7a #eda100 #e87ba4 #008300`), which clears colourblind
separation on every adjacent pair; DESIGN.md still governs the typography
(Times New Roman for prose, a fixed-width face for every number) and the report's
rules and headings. Three of the six slots sit below 3:1 against the chart
surface, which obliges visible labels: every multi-series panel is direct-labelled
and the report carries the full table.

Side is encoded twice over -- hue AND marker fill -- so the right/left
distinction survives a greyscale print, which is the one this report is most
likely to be read on.

Usage:
    python cohort_figures.py [--scores context/cohort/cohort_scores.json]
        [--out context/cohort/figures]
"""
import argparse
import logging
import textwrap
import json
from collections import OrderedDict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # no display on a batch run

import matplotlib.pyplot as plt
import numpy as np


def _load_theme():
    """figure_theme by path, matching how this file reaches its siblings."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_theme_for_cohort_figures",
        Path(__file__).resolve().parent / "figure_theme.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The palette moved to figure_theme.py on 2026-09-04. It was reasoned out and
# CVD-validated here first, and figure_theme adopted this file's choices
# wholesale rather than the reverse -- the names below are kept as aliases so
# this file's own prose and its ~50 use sites still read the way they did.
#
# What changed in the move: the neutrals. This file carried near-misses of
# DESIGN.md's ramp (#fcfcfb against #FFFFFF, #0b0b0b against #1F2421,
# #e1e0d9 against #D8DBD7), which was drift rather than a decision, so they
# now come from the one place that defines them. The figures regenerate into
# the gitignored context/ folder, so nothing tracked changes shape.
_theme = _load_theme()

SERIES = list(_theme.SERIES)
SIDE_COLOUR = dict(_theme.LIMB)
SIDE_MARKER = {side: style["marker"]
               for side, style in _theme.LIMB_STYLE.items()}
V_UCM_COLOUR = _theme.V_UCM
V_ORT_COLOUR = _theme.V_ORT

SURFACE = _theme.SURFACE
INK = _theme.INK
INK_2 = _theme.INK_2
MUTED = _theme.BASELINE
GRID = _theme.GRID
BASELINE = _theme.BORDER
# DESIGN.md's normative-agreement green, used only for the GDI reference band.
BAND = _theme.NORMATIVE_BAND[0]["color"]
BAND_LINE = _theme.NORMATIVE_MEAN_LINE

PROSE = ["Times New Roman", "DejaVu Serif", "serif"]
DATA = ["Cascadia Code", "Consolas", "DejaVu Sans Mono", "monospace"]

# DESIGN.md's data face is Cascadia Code falling back to Consolas, and Consolas
# is the one actually installed here. matplotlib logs a findfont warning per
# text object for the missing head of the list -- hundreds of lines for a run
# whose outcome is the documented fallback working exactly as specified. The
# list stays as DESIGN.md orders it; only the noise is silenced.
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

GDI_NORMATIVE_MEAN = 100.0
GDI_NORMATIVE_SD = 10.0


def style():
    """DESIGN.md typography over the dataviz chart chrome.

    Numbers wear the fixed-width face (tick labels, annotations); prose wears
    the serif. That is DESIGN.md's rule for the GUI applied to a figure, where
    the tick labels *are* the data readout.
    """
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.family": PROSE,
        "font.size": 9,
        "axes.edgecolor": BASELINE,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "normal",
        "axes.labelsize": 9,
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "lines.linewidth": 2.0,
        "lines.markersize": 8,
    })


def _mono(axis):
    """Tick labels in the data face. Applied after the ticks are final."""
    for label in list(axis.get_xticklabels()) + list(axis.get_yticklabels()):
        label.set_fontfamily(DATA)


def _caption(figure, text, width=96):
    """A wrapped caption under the figure.

    Wrapped explicitly rather than left to matplotlib's `wrap=True`, which
    measures against the axes and not the saved canvas: with
    `bbox_inches="tight"` a long unwrapped caption sets the output width, and
    the plot ends up a narrow column at the left of a very wide image. Every
    caption in this module goes through here for that reason.
    """
    figure.text(0.0, -0.02, "\n".join(textwrap.wrap(text, width)),
                fontsize=7.5, color=INK_2, style="italic", va="top", ha="left",
                transform=figure.transFigure)


def _nudge_labels(positions, minimum_gap):
    """Spread overlapping end-of-line labels apart, order preserved.

    Six lines converging at the right edge of a panel land their labels on top
    of one another; a direct label that cannot be read is worse than no direct
    label, and these panels need theirs because three of the six palette slots
    sit under 3:1 against the surface.
    """
    order = sorted(range(len(positions)), key=lambda i: positions[i])
    out = list(positions)
    for rank in range(1, len(order)):
        below, here = order[rank - 1], order[rank]
        if out[here] - out[below] < minimum_gap:
            out[here] = out[below] + minimum_gap
    return out


def _label_offset(pair, distance=15.0):
    """Where to put a participant's name so it misses that participant's points.

    The two limbs sit either side of the mean, so any offset along the line
    joining them lands on one of them. Offset perpendicular to it instead,
    taking the rightward normal so labels read outward from the cloud. Falls
    back to up-and-right when the two limbs coincide and there is no line.
    """
    if len(pair) < 2:
        return (11, 6)
    # Scaled to the axes' own ranges before rotating, or a 20-unit GDI spread
    # against a 0.7 Delta-V spread would make every normal point almost
    # straight up.
    dx = (pair[1]["gdi"] - pair[0]["gdi"]) / 20.0
    dy = (pair[1]["delta_v"] - pair[0]["delta_v"]) / 0.7
    length = float(np.hypot(dx, dy))
    if length < 1e-9:
        return (11, 6)
    return (distance * dy / length, -distance * dx / length)


def _despine(axis, keep=("left", "bottom")):
    for name, spine in axis.spines.items():
        spine.set_visible(name in keep)


def participant_order(rows):
    """Participants by cohort GDI, best first.

    One order, shared by every figure that lists participants, so a reader
    comparing figure 1 against figure 2 is comparing the same rows in the same
    places rather than re-finding each name.
    """
    means = OrderedDict()
    for row in rows:
        means.setdefault(row["participant"], []).append(row["gdi"])
    return [name for name, _ in sorted(means.items(),
                                       key=lambda kv: -np.mean(kv[1]))]


def colours_for(order):
    return {name: SERIES[index % len(SERIES)] for index, name in enumerate(order)}


def _row(rows, participant, side):
    for row in rows:
        if row["participant"] == participant and row["side"] == side:
            return row
    return None


def figure_gdi(rows, order, path):
    """GDI per limb against the normative band.

    A dot plot, not bars: GDI has no meaningful zero -- it is a log-distance
    rescaled so the control mean is 100 -- and a bar drawn from zero would
    invite a reader to compare bar lengths as ratios, which they are not.
    Whiskers are +/- 1 SD of the per-stride scores, so within-limb spread and
    between-limb spread are legible on the same axis.
    """
    figure, axis = plt.subplots(figsize=(6.5, 3.6))
    axis.axvspan(GDI_NORMATIVE_MEAN - GDI_NORMATIVE_SD,
                 GDI_NORMATIVE_MEAN + GDI_NORMATIVE_SD,
                 color=BAND, zorder=0)
    axis.axvline(GDI_NORMATIVE_MEAN, color=BAND_LINE, linewidth=1.0,
                 zorder=1, alpha=0.7)

    positions = {name: len(order) - index for index, name in enumerate(order)}
    offset = 0.16
    for side in ("right", "left"):
        drawn = [(positions[name] + (offset if side == "right" else -offset),
                  _row(rows, name, side)) for name in order]
        drawn = [(y, r) for y, r in drawn if r]
        axis.errorbar([r["gdi"] for _, r in drawn], [y for y, _ in drawn],
                      xerr=[r["gdi_sd"] or 0 for _, r in drawn],
                      fmt=SIDE_MARKER[side], color=SIDE_COLOUR[side],
                      ecolor=SIDE_COLOUR[side], elinewidth=1.4, capsize=0,
                      markersize=7, markeredgecolor=SURFACE,
                      markeredgewidth=1.2, label=side, zorder=3)

    axis.set_yticks(list(positions.values()))
    axis.set_yticklabels(list(positions.keys()))
    axis.set_ylim(0.4, len(order) + 0.6)
    axis.set_xlabel("Gait Deviation Index  (100 = control mean, 10 = 1 SD)")
    axis.set_title("Figure 1.  GDI per limb, pooled over every stride in the session",
                   loc="left", pad=22)
    axis.grid(axis="y", visible=False)
    # Above the plot, not inside it: the data spans the full width of the axes
    # and every in-axes corner is occupied by a limb.
    axis.legend(loc="lower left", bbox_to_anchor=(0, 1.0, 1, 0.1), ncol=2,
                borderaxespad=0)
    _despine(axis)
    _mono(axis)
    figure.tight_layout()
    _caption(figure,
             "Whiskers are +/- 1 SD of the per-stride scores. The shaded band "
             "is the normative 100 +/- 10; the rule at 100 is the control mean. "
             "Participants are ordered by their two-limb mean, and every "
             "later figure keeps this order.")
    figure.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(figure)


def figure_synergy(rows, order, path):
    """Delta-V per limb.

    Bars here and dots in figure 1, deliberately: Delta-V has a true and
    meaningful zero -- equal variance per DOF inside and outside the
    uncontrolled manifold, meaning no synergy -- so length from zero is the
    quantity, and the sign is the finding.
    """
    figure, axis = plt.subplots(figsize=(6.5, 3.6))
    positions = {name: len(order) - index for index, name in enumerate(order)}
    height = 0.30
    for side in ("right", "left"):
        drawn = [(positions[name] + (height / 2 + 0.02 if side == "right"
                                     else -height / 2 - 0.02),
                  _row(rows, name, side)) for name in order]
        drawn = [(y, r) for y, r in drawn if r and r["delta_v"] is not None]
        axis.barh([y for y, _ in drawn], [r["delta_v"] for _, r in drawn],
                  height=height, color=SIDE_COLOUR[side], label=side,
                  edgecolor=SURFACE, linewidth=1.0, zorder=3)
        for y, row in drawn:
            value = row["delta_v"]
            axis.text(value + (0.012 if value >= 0 else -0.012), y,
                      f"{value:+.2f}", va="center",
                      ha="left" if value >= 0 else "right",
                      fontsize=7, family=DATA, color=INK_2, zorder=4)

    axis.axvline(0, color=BASELINE, linewidth=1.0, zorder=2)
    axis.set_yticks(list(positions.values()))
    axis.set_yticklabels(list(positions.keys()))
    axis.set_ylim(0.4, len(order) + 0.6)
    axis.set_xlim(-0.32, 0.62)
    axis.set_xlabel(r"Synergy index  $\Delta V = (V_{UCM} - V_{ORT}) / V_{TOT}$,"
                    "  per DOF")
    axis.set_title("Figure 2.  Synergy index per limb, averaged over the gait cycle",
                   loc="left", pad=22)
    axis.grid(axis="y", visible=False)
    axis.legend(loc="lower left", bbox_to_anchor=(0, 1.0, 1, 0.1), ncol=2,
                borderaxespad=0)
    _despine(axis)
    _mono(axis)
    figure.tight_layout()
    _caption(figure,
             "Positive: joint variance is channelled into directions that leave "
             "the pelvis-relative centre of mass alone, which is a synergy. "
             "Negative: the variance is pushing the centre of mass around. "
             "Participant order matches Figure 1, so the two figures can be read "
             "row against row.")
    figure.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(figure)


def figure_comparison(rows, order, summary, path):
    """The one figure the report exists for: GDI against Delta-V.

    Twelve limbs, but only six participants -- the two limbs of one person are
    not independent observations, so both correlations are printed and the
    participant means are drawn as the larger markers the eye should weight.
    """
    colours = colours_for(order)
    figure, axis = plt.subplots(figsize=(6.5, 4.4))

    paired = [r for r in rows if r["delta_v"] is not None]
    x = np.array([r["gdi"] for r in paired])
    y = np.array([r["delta_v"] for r in paired])
    if x.size > 2:
        fit = np.poly1d(np.polyfit(x, y, 1))
        span = np.linspace(x.min() - 1.5, x.max() + 1.5, 50)
        axis.plot(span, fit(span), "--", color=MUTED, linewidth=1.2,
                  zorder=1, label="least squares (12 limbs)")

    axis.axhline(0, color=BASELINE, linewidth=1.0, zorder=1)
    for name in order:
        for side in ("right", "left"):
            row = _row(rows, name, side)
            if not row or row["delta_v"] is None:
                continue
            axis.plot(row["gdi"], row["delta_v"], SIDE_MARKER[side],
                      color=colours[name] if side == "right" else SURFACE,
                      markeredgecolor=colours[name], markeredgewidth=1.8,
                      markersize=8, zorder=3)
        # The participant mean, direct-labelled. Three of the six palette slots
        # sit under 3:1 against the surface, so the name carries identity and
        # the hue only reinforces it.
        both = [_row(rows, name, s) for s in ("right", "left")]
        both = [r for r in both if r and r["delta_v"] is not None]
        if both:
            mx = float(np.mean([r["gdi"] for r in both]))
            my = float(np.mean([r["delta_v"] for r in both]))
            axis.plot(mx, my, "P", color=colours[name], markersize=11,
                      markeredgecolor=SURFACE, markeredgewidth=1.4, zorder=4)
            # Offset perpendicular to the line joining the two limbs, so the
            # name lands in the gap beside the pair rather than on top of the
            # limb that happens to sit up and to the right. A fixed offset put
            # CK's label on CK's left limb.
            axis.annotate(name, (mx, my), textcoords="offset points",
                          xytext=_label_offset(both), fontsize=9, color=INK,
                          family=DATA, zorder=5)

    def stat_line(label, entry):
        if not entry:
            return None
        return (f"{label:<15}r = {entry['r']:+.2f}   rho = {entry['rho']:+.2f}"
                f"   p = {entry['p']:.3f}")

    note = [line for line in (
        stat_line(f"{(summary.get('gdi_vs_delta_v') or {}).get('n', 0)} limbs",
                  summary.get("gdi_vs_delta_v")),
        stat_line("6 participants", summary.get("gdi_vs_delta_v_participant")),
    ) if line]
    if note:
        # Bottom left: the fit runs top-left to bottom-right, so this corner and
        # the top-right one are the two the data leaves empty. The legend takes
        # the other.
        axis.text(0.02, 0.03, "\n".join(note), transform=axis.transAxes,
                  fontsize=8, family=DATA, color=INK, va="bottom",
                  bbox=dict(boxstyle="round,pad=0.45", facecolor=SURFACE,
                            edgecolor=GRID, linewidth=0.8), zorder=6)

    axis.margins(x=0.10, y=0.20)
    axis.set_xlabel("Gait Deviation Index")
    axis.set_ylabel(r"Synergy index  $\Delta V$")
    axis.set_title("Figure 3.  A limb closer to the normative pattern shows less "
                   "centre-of-mass synergy, not more", loc="left", pad=30)
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=MUTED,
                   markeredgecolor=MUTED, markersize=8, label="right limb"),
        plt.Line2D([], [], marker="s", linestyle="", color=SURFACE,
                   markeredgecolor=MUTED, markeredgewidth=1.8, markersize=8,
                   label="left limb"),
        plt.Line2D([], [], marker="P", linestyle="", color=MUTED,
                   markersize=11, label="participant mean"),
        plt.Line2D([], [], linestyle="--", color=MUTED, linewidth=1.2,
                   label="least squares"),
    ]
    axis.legend(handles=handles, loc="lower left",
                bbox_to_anchor=(0, 1.0, 1, 0.1), ncol=4, borderaxespad=0)
    _despine(axis)
    _mono(axis)
    figure.tight_layout()
    _caption(figure,
             "Marker fill encodes side as well as hue, so the distinction "
             "survives a greyscale print, and each participant mean is "
             "direct-labelled. The two limbs of one participant are not "
             "independent observations; the participant-level correlation is the "
             "conservative one and the one to quote.")
    figure.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(figure)


def figure_cycle(sessions, order, path):
    """Delta-V across the normalised gait cycle, one panel per side.

    The cycle-averaged number in figure 2 hides where in the stride the joints
    are co-varying, which is the substance of a UCM analysis: a limb can be
    synergistic through stance and not through swing, and that reads as a
    middling average.
    """
    colours = colours_for(order)
    by_name = {s["participant"]: s for s in sessions}
    figure, axes = plt.subplots(1, 2, figsize=(7.4, 3.4), sharey=True)

    curves = {}
    for side in ("right", "left"):
        for name in order:
            synergy = (by_name.get(name, {}).get("synergy") or {}).get(side)
            if synergy:
                curves[(side, name)] = np.asarray(
                    synergy["per_phase"]["delta_v"], dtype=float)
    if not curves:
        return
    low = min(float(v.min()) for v in curves.values())
    high = max(float(v.max()) for v in curves.values())
    pad = (high - low) * 0.06
    gap = (high - low) * 0.055     # minimum vertical separation between labels

    for axis, side in zip(axes, ("right", "left")):
        axis.axhline(0, color=BASELINE, linewidth=1.0, zorder=2)
        drawn = [name for name in order if (side, name) in curves]
        ends = _nudge_labels([float(curves[(side, n)][-1]) for n in drawn], gap)
        for name, label_y in zip(drawn, ends):
            values = curves[(side, name)]
            phase = np.linspace(0, 100, values.size)
            axis.plot(phase, values, color=colours[name], linewidth=1.5,
                      zorder=3, label=name)
            axis.annotate(name, (104, label_y), fontsize=7, family=DATA,
                          color=colours[name], va="center", zorder=4,
                          annotation_clip=False)
        axis.set_xlim(0, 116)
        axis.set_ylim(low - pad, high + pad)
        axis.set_xticks([0, 25, 50, 75, 100])
        axis.set_xlabel("% gait cycle")
        axis.set_title(f"{side} limb", fontsize=9.5, color=INK_2, loc="left")
        _despine(axis)
        _mono(axis)

    axes[0].set_ylabel(r"$\Delta V$")
    figure.suptitle(r"Figure 4.  Where in the stride the synergy is: $\Delta V$ "
                    "by phase", fontsize=11, y=1.03, x=0.0, ha="left")
    figure.tight_layout()
    _caption(figure,
             "Above the rule, joint variance stabilises the centre of mass; "
             "below it, the variance is pushing the centre of mass around. The "
             "cycle-averaged value in Figure 2 hides this: a limb can be "
             "synergistic through stance and not through swing and still average "
             "to nothing. Lines are direct-labelled at the end of the cycle, "
             "nudged apart where they converge.")
    figure.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(figure)


def figure_trial_order(sessions, order, path):
    """GDI against trial number, one panel per participant.

    Trial order should not predict a score: every trial is converted, calibrated
    and segmented independently, so a monotonic slide along this axis is
    something moving in the recording rather than in the participant. This is
    the check that caught the foot-progression-angle defect (see
    docs/2026-08-31-an-gdi-decline.md), and it is here so the cohort's numbers
    can be read knowing it was run.
    """
    by_name = {s["participant"]: s for s in sessions}
    figure, axes = plt.subplots(2, 3, figsize=(7.0, 4.4), sharey=True)

    for axis, name in zip(axes.ravel(), order):
        axis.axhspan(GDI_NORMATIVE_MEAN - GDI_NORMATIVE_SD,
                     GDI_NORMATIVE_MEAN + GDI_NORMATIVE_SD,
                     color=BAND, zorder=0)
        session = by_name.get(name, {})
        for side in ("right", "left"):
            series = (session.get("by_trial") or {}).get(side) or {}
            values = list(series.values())
            if not values:
                continue
            trials = np.arange(1, len(values) + 1)
            axis.plot(trials, values, SIDE_MARKER[side] + "-",
                      color=SIDE_COLOUR[side], markersize=3.5, linewidth=1.2,
                      zorder=3, label=side)
            if len(values) > 2 and np.ptp(values) > 0:
                r = float(np.corrcoef(trials, values)[0, 1])
                axis.text(0.04, 0.06 if side == "left" else 0.20,
                          f"{side[0]} r={r:+.2f}", transform=axis.transAxes,
                          fontsize=7, family=DATA, color=SIDE_COLOUR[side])
        axis.set_title(name, fontsize=9.5, color=INK, family=DATA, loc="left")
        axis.set_xlim(0.4, 15.6)
        axis.set_xticks([1, 5, 10, 15])
        _despine(axis)
        _mono(axis)

    for axis in axes[1]:
        axis.set_xlabel("trial (session order)")
    for axis in axes[:, 0]:
        axis.set_ylabel("GDI")
    # One legend for the whole grid, above it: repeating it in six panels would
    # spend six times the ink on one two-level distinction, and inside any panel
    # it lands on the trend annotations.
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(handles[:2], labels[:2], loc="upper right",
                  bbox_to_anchor=(1.0, 1.035), ncol=2, frameon=False)
    figure.suptitle("Figure 5.  GDI by trial order -- the drift check",
                    fontsize=11, y=1.03, x=0.0, ha="left")
    figure.tight_layout()
    # Row 2's panel titles land on row 1's tick labels at the default spacing.
    figure.subplots_adjust(hspace=0.42)
    _caption(figure,
             "Trials are processed independently, so trial number should not "
             "predict a score. A monotonic trend indicates drift in the "
             "recording rather than a change in the participant; r is the "
             "correlation of GDI with trial number, per limb. Shaded band is "
             "the normative 100 +/- 10.")
    figure.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(figure)


def figure_variance(rows, order, path):
    """The decomposition Delta-V is a ratio of, limb by limb.

    Delta-V is scale-free by construction, which is what makes it comparable
    across participants -- and also what hides a thirty-fold range in how much
    these limbs vary stride to stride at all. Two limbs can share a Delta-V and
    mean very different things about the recording, so the raw decomposition is
    reported beside the ratio.

    A paired dot per limb rather than a V_UCM-against-V_ORT scatter: the two
    quantities are nearly equal by construction, so a scatter piles every point
    onto the diagonal, and a log scale wide enough for SB crushes the other
    five participants into one blob. On a shared log axis the pair separates,
    and which of the two sits further right IS the sign of Delta-V.
    """
    colours = colours_for(order)
    figure, axis = plt.subplots(figsize=(6.5, 4.2))

    labels, positions = [], []
    for index, name in enumerate(order):
        for side in ("right", "left"):
            row = _row(rows, name, side)
            if not row or row["v_ucm"] is None:
                continue
            y = len(order) * 2 - (index * 2 + (0 if side == "right" else 0.72))
            positions.append(y)
            labels.append(f"{name} {side[0].upper()}")
            axis.plot([row["v_ort"], row["v_ucm"]], [y, y], "-",
                      color=colours[name], linewidth=1.6, alpha=0.45, zorder=2)
            axis.plot(row["v_ort"], y, "o", color=V_ORT_COLOUR, markersize=7,
                      markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=3)
            axis.plot(row["v_ucm"], y, "o", color=V_UCM_COLOUR, markersize=7,
                      markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=4)
            axis.annotate(f"{row['delta_v']:+.2f}", (max(row["v_ort"],
                                                         row["v_ucm"]), y),
                          textcoords="offset points", xytext=(9, 0),
                          fontsize=7, family=DATA, color=INK_2, va="center",
                          zorder=5)

    axis.set_xscale("log")
    axis.set_yticks(positions)
    axis.set_yticklabels(labels)
    axis.set_ylim(min(positions) - 0.9, max(positions) + 0.9)
    axis.set_xlim(min(r["v_ort"] for r in rows if r["v_ort"]) * 0.5,
                  max(r["v_ucm"] for r in rows if r["v_ucm"]) * 3.0)
    axis.set_xlabel(r"variance per DOF  (deg$^2$, log scale)")
    axis.set_title("Figure 6.  The variance decomposition behind the ratio",
                   loc="left", pad=22)
    axis.grid(axis="y", visible=False)
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=V_UCM_COLOUR,
                   markersize=7, label=r"$V_{UCM}$  (uncontrolled manifold, 15 DOF)"),
        plt.Line2D([], [], marker="o", linestyle="", color=V_ORT_COLOUR,
                   markersize=7, label=r"$V_{ORT}$  (orthogonal, 3 DOF)"),
    ]
    axis.legend(handles=handles, loc="lower left",
                bbox_to_anchor=(0, 1.0, 1, 0.1), ncol=2, borderaxespad=0)
    _despine(axis)
    _mono(axis)
    figure.tight_layout()
    _caption(figure,
             "V_UCM to the right of V_ORT is a synergy; the trailing number is "
             "that limb's Delta-V. Position along the axis is how much these "
             "strides vary at all, and it is not a detail: SB's limbs carry an "
             "order of magnitude more joint variance than anyone else's, and "
             "HH's right limb carries the least, so both of their near-zero "
             "ratios rest on very different amounts of data. Where a limb's two "
             "dots coincide, its Delta-V is near zero.")
    figure.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(figure)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--scores", default="context/cohort/cohort_scores.json")
    parser.add_argument("--out", default="context/cohort/figures")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.scores).read_text(encoding="utf-8"))
    summary = payload["summary"]
    rows = summary["rows"]
    sessions = payload["sessions"]
    order = participant_order(rows)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    style()

    built = [
        ("fig1_gdi_by_limb.png", lambda p: figure_gdi(rows, order, p)),
        ("fig2_synergy_by_limb.png", lambda p: figure_synergy(rows, order, p)),
        ("fig3_gdi_vs_synergy.png",
         lambda p: figure_comparison(rows, order, summary, p)),
        ("fig4_synergy_across_cycle.png",
         lambda p: figure_cycle(sessions, order, p)),
        ("fig5_gdi_trial_order.png",
         lambda p: figure_trial_order(sessions, order, p)),
        ("fig6_variance_decomposition.png",
         lambda p: figure_variance(rows, order, p)),
    ]
    for name, builder in built:
        builder(out / name)
        print(f"-> {out / name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
