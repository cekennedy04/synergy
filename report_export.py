"""
report_export.py

U5 of the clinician trial report GUI plan: exports the currently reviewed
trial's report (metadata, joint-angle plots, gait metrics, confidence
indicators) to a single PDF file in one action (R10), via
matplotlib.backends.backend_pdf.PdfPages (KTD2).

Pure w.r.t. Tk -- this module never imports tkinter. clinician_gui.py's own
Export button click handler is the only code that touches tkinter for this
unit (the asksaveasfilename prompt and the showinfo/showerror confirmation);
this module only consumes already-shaped data (shape_results_for_display's
output, defined in clinician_gui.py) and already-built matplotlib Figure
objects (built once, for on-screen display, by
clinician_gui.build_curve_figure -- reused here rather than re-plotted, per
KTD2), and writes them to a PDF.

Every page's content comes from the shaped_results/figures already passed
in -- this module never recomputes pipeline results and never calls
run_pipeline/gait_analysis itself.

A results object with an unavailable section (a curve marked
available: False, a metrics row reporting "not available", or a
confidence-unavailable trial) still produces a page/row with a clear "not
available" note here -- it never raises and never aborts the rest of the
export.
"""
import importlib.util
import os
import sys
import textwrap

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

PAGE_SIZE = (8.5, 11)  # inches -- US Letter, matches PdfPages' own default assumption of one Figure per page.

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_MODULE_LOADING_PATH = os.path.join(_REPO_ROOT, "module_loading.py")
_REPORT_FORMATTING_PATH = os.path.join(_REPO_ROOT, "report_formatting.py")
_FIGURE_THEME_PATH = os.path.join(_REPO_ROOT, "figure_theme.py")


def _bootstrap_load_module_loading():
    # One-off bootstrap for module_loading.py itself, matching
    # clinician_gui.py's own bootstrap -- it can't load itself via its own
    # not-yet-loaded function. Registered under the same fixed sys.modules
    # key ("module_loading") clinician_gui.py's bootstrap uses, so both
    # files' loaders share the exact same module object -- and therefore the
    # same _LOADED_MODULE_CACHE dict -- instead of each independently
    # loading and executing module_loading.py (and, transitively,
    # report_formatting.py) a second time.
    existing = sys.modules.get("module_loading")
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location("module_loading", _MODULE_LOADING_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["module_loading"] = module
    spec.loader.exec_module(module)
    return module


_module_loading = _bootstrap_load_module_loading()
_report_formatting = _module_loading.load_module_by_path(
    "report_formatting_for_report_export", _REPORT_FORMATTING_PATH
)
# Loaded by path like its sibling above rather than imported by name: this
# module is itself loaded by path from clinician_gui.py, where the repo root
# is not guaranteed to be on sys.path.
theme = _module_loading.load_module_by_path(
    "figure_theme_for_report_export", _FIGURE_THEME_PATH
)


def _wrapped_note(axis, x, y, text, width=88, fontsize=9, line_height=0.018):
    """Draw an italic note, wrapped explicitly, and return the new y.

    matplotlib's own `wrap=True` measures against the *figure* width and is
    unreliable on a text placed in axes coordinates: the GDI basis line ran
    straight off the right edge of the page, taking with it the sentence
    saying the score covers the session rather than this trial -- which is
    the caveat that most needed reading. textwrap is deterministic, and it is
    what gait_event_picker_ui already uses for the same reason.
    """
    lines = textwrap.wrap(text, width) or [""]
    for line in lines:
        axis.text(x, y, line, fontsize=fontsize, style="italic", va="top",
                  transform=axis.transAxes)
        y -= line_height
    return y


def _cell(text, width=22):
    """One table cell's text, wrapped onto as many lines as it needs.

    matplotlib's table does not clip an over-long cell -- it draws straight
    through its neighbour, so a long "not available" reason rendered on top of
    the adjacent leg's number and read as that leg's value.
    """
    return "\n".join(textwrap.wrap(str(text), width) or [""])


def _new_text_page():
    figure = Figure(figsize=PAGE_SIZE, dpi=100)
    axis = figure.add_subplot(111)
    axis.axis("off")
    return figure, axis


def _build_metadata_page(metadata):
    """Metadata title page (U5 Approach step 2, first sub-item): renders
    shaped_results["metadata"] as plain text on a blank Figure."""
    metadata = metadata or {}
    figure, axis = _new_text_page()

    rows = [
        ("Subject / session", metadata.get("subject_session_id")),
        ("Trial", metadata.get("trial_name")),
        ("Date", metadata.get("date")),
        ("Duration", metadata.get("duration_display")),
        ("Sensor coverage", metadata.get("sensor_coverage")),
        ("Root translation", metadata.get("translation_type")),
        ("Gait speed method", metadata.get("gait_speed_method")),
    ]
    lines = [f"{label}: {value if value not in (None, '') else 'not available'}" for label, value in rows]

    axis.text(
        0.05, 0.95, "Clinician Trial Report", fontsize=18, fontweight="bold",
        va="top", ha="left", transform=axis.transAxes,
    )
    axis.text(
        0.05, 0.85, "\n".join(lines), fontsize=12, va="top", ha="left",
        family="monospace", transform=axis.transAxes,
    )

    # Spatial metrics here are inferred, not tracked (see clinician_gui's
    # SPATIAL_PROVENANCE). A metadata row alone is easy to skim past, so the
    # limitation is also stated in prose on the page carrying the numbers.
    if metadata.get("spatial_displacement_validated") is False:
        # _wrapped_note, not wrap=True: matplotlib wraps against the figure
        # width, so a note starting at x=0.05 got a left margin and no right
        # one -- the last line ran flush into the page edge.
        _wrapped_note(
            axis, 0.05, 0.32,
            "Note: this pipeline's inverse kinematics solves orientations "
            "only, with root translation pinned. Gait speed and stride length "
            "are therefore inferred from stance-phase foot velocity rather "
            "than measured from global displacement, and are not independent "
            "of one another. Cadence is derived from event timing and is "
            "unaffected.")
    return figure


def _build_summary_page(summary):
    """Headline scores page (added 2026-09-01), rendered second, straight
    after the title page.

    These were previously only rows near the bottom of the metrics table on
    page 8, which is not where a reader looks for the two numbers the analysis
    exists to produce. Identity stays on page 1 -- a score before you know
    whose trial it belongs to is worse than a score one page later.

    Returns None when there is nothing to show, so the page is skipped rather
    than printed empty.
    """
    summary = summary or {}
    gdi = summary.get("gdi") or {}
    synergy = summary.get("synergy") or {}
    unavailable = summary.get("unavailable")
    if not gdi and not synergy and not unavailable:
        return None

    figure, axis = _new_text_page()
    axis.text(0.05, 0.95, "Summary scores", fontsize=18, fontweight="bold",
              va="top", ha="left", transform=axis.transAxes)

    # A stated reason, not a missing page. A report that simply omits the
    # scores looks the same as one whose scores were fine, and the reader
    # cannot tell which they are holding.
    if unavailable:
        axis.text(0.05, 0.85, "Not available", fontsize=13,
                  fontweight="bold", va="top", transform=axis.transAxes)
        _wrapped_note(axis, 0.05, 0.79, unavailable, fontsize=10,
                      line_height=0.020)
        return figure

    y = 0.82
    if gdi:
        axis.text(0.05, y, "Gait Deviation Index", fontsize=13,
                  fontweight="bold", va="top", transform=axis.transAxes)
        y -= 0.06
        # Large, because this is the number the page exists for.
        axis.text(0.08, y, f"Right   {gdi.get('right_display', 'not available')}",
                  fontsize=22, va="top", family="monospace",
                  transform=axis.transAxes)
        y -= 0.075
        axis.text(0.08, y, f"Left    {gdi.get('left_display', 'not available')}",
                  fontsize=22, va="top", family="monospace",
                  transform=axis.transAxes)
        y -= 0.055
        y = _wrapped_note(axis, 0.08, y, gdi.get("basis", ""))
        y -= 0.07

    if synergy:
        axis.text(0.05, y, "Synergy index", fontsize=13, fontweight="bold",
                  va="top", transform=axis.transAxes)
        y -= 0.06
        axis.text(0.08, y, f"dV      {synergy.get('value_display', 'not available')}",
                  fontsize=22, va="top", family="monospace",
                  transform=axis.transAxes)
        y -= 0.055
        # The task variable is not a footnote: the ranking between
        # methodologies reverses with it, so a dV without it is not
        # interpretable.
        for line in synergy.get("notes", []):
            y = _wrapped_note(axis, 0.08, y, line)
            y -= 0.017

    # Said out loud when there is no synergy block at all. A page headed
    # "Summary scores" that carries one score reads as though the other was
    # not computed, or worse as though this analysis has only one; the note
    # says it is a deliberate omission and where the number lives.
    note = summary.get("synergy_note")
    if note and not synergy:
        axis.text(0.05, y, "Synergy index", fontsize=13, fontweight="bold",
                  va="top", transform=axis.transAxes)
        y -= 0.06
        _wrapped_note(axis, 0.08, y, note)
    return figure


def _build_gdi_figure(gdi_scores):
    """GDI per side against the normative band, with each stride shown.

    The band is the point: GDI is defined so 100 is the control mean and every
    10 points is one standard deviation below it, so a bare number means
    nothing to a reader who does not already know that. Individual strides are
    plotted because a mean over four scattered strides is much weaker evidence
    than one over four tight ones, and the mean alone hides which you have.
    """
    if not gdi_scores:
        return None
    sides = [(name, gdi_scores.get(name)) for name in ("right", "left")]
    if not any(entry for _name, entry in sides):
        return None

    figure = Figure(figsize=PAGE_SIZE, dpi=100)
    axis = figure.add_subplot(111)

    # The band is a confidence statement in the same language as the
    # per-segment tiers, so it is drawn in the semantic tokens rather than in
    # a green and an amber invented for this one figure.
    for band in theme.NORMATIVE_BAND:
        axis.axhspan(band["low"], band["high"], color=band["color"], alpha=0.7,
                     zorder=0, label=band["label"])
    axis.axhline(100, color=theme.NORMATIVE_MEAN_LINE, linewidth=1.2, zorder=1)

    for position, (name, entry) in enumerate(sides):
        if not entry:
            continue
        style = theme.limb_style(name)
        strides = entry.get("per_stride") or []
        if strides:
            axis.plot([position] * len(strides), strides,
                      linestyle="none", marker=style["marker"],
                      color=theme.LIMB_TINT[name], markersize=6, alpha=0.9,
                      markeredgecolor=style["color"], markeredgewidth=0.6,
                      zorder=2)
        # Marker shape carries the limb alongside hue, per figure_theme's rule
        # that no figure here distinguishes limbs by colour alone.
        axis.plot([position], [entry["mean"]], linestyle="none",
                  marker=style["marker"], color=style["color"],
                  markersize=11, markeredgecolor=theme.SURFACE, zorder=3)
        axis.annotate(f"{entry['mean']:.1f}", (position, entry["mean"]),
                      textcoords="offset points", xytext=(16, -4), fontsize=12,
                      fontweight="bold", color=style["color"])

    axis.set_xticks([0, 1])
    axis.set_xticklabels(["Right", "Left"], fontsize=12)
    axis.set_xlim(-0.5, 1.5)
    axis.set_ylabel("Gait Deviation Index", fontsize=11)
    axis.set_title("GDI against the normative range", fontsize=14, pad=14)
    theme.style_axis(axis, grid_axis="y")

    # The mean/stride entries are drawn as neutral proxies rather than as
    # whichever limb happened to be plotted first. While both limbs shared one
    # colour a "trial mean" swatch was accurate for both; now that colour
    # carries the limb, a blue swatch labelled "trial mean" would be a
    # statement about the right leg standing in for a key to the whole figure,
    # and the left leg would have no entry at all. Colour is explained by the
    # x axis; the legend explains size and shape.
    from matplotlib.lines import Line2D
    proxies = [
        Line2D([], [], linestyle="none", marker="o", markersize=11,
               color=theme.INK_2, label="trial mean"),
        Line2D([], [], linestyle="none", marker="o", markersize=6,
               color=theme.BASELINE, label="individual strides"),
    ]
    handles, labels = axis.get_legend_handles_labels()
    # 'best', not 'lower right'. A poor GDI is a low GDI, so the bottom of
    # this axis is exactly where an impaired limb's strides land -- the fixed
    # corner was covering the worst limb in the trial, which is the one a
    # clinician opened the report to look at. Same argument as the picker's
    # legend placement.
    axis.legend(handles + proxies, labels + [p.get_label() for p in proxies],
                loc="best", fontsize=8, framealpha=0.9)
    figure.tight_layout()
    return figure


def _build_synergy_figure(synergy):
    """Variance decomposition across the gait cycle.

    The cycle-mean dV on the summary page says whether a synergy is present on
    average; this says *where*. A trial can average positive while being
    negative through single support, and only the per-phase curve shows that.
    """
    per_phase = (synergy or {}).get("per_phase") or {}
    delta_v = per_phase.get("delta_v") or []
    if not delta_v:
        return None

    x = [i * 100.0 / (len(delta_v) - 1) for i in range(len(delta_v))]         if len(delta_v) > 1 else [0.0]

    figure = Figure(figsize=PAGE_SIZE, dpi=100)
    top = figure.add_subplot(211)
    top.axhline(0, color=theme.ZERO_LINE, linewidth=1)
    top.plot(x, delta_v, color=theme.V_UCM, linewidth=1.8)
    top.fill_between(x, 0, delta_v, where=[v > 0 for v in delta_v],
                     color=theme.V_UCM, alpha=0.20, interpolate=True)
    top.fill_between(x, 0, delta_v, where=[v <= 0 for v in delta_v],
                     color=theme.V_ORT, alpha=0.20, interpolate=True)
    top.set_ylabel("dV", fontsize=10)
    top.set_title(f"Synergy across the gait cycle -- {synergy.get('task_variable', '')}",
                  fontsize=13, pad=12)
    theme.style_axis(top)
    top.text(0.01, 0.95, "above zero: joints co-vary to stabilise the task",
             transform=top.transAxes, fontsize=8, va="top", style="italic")

    bottom = figure.add_subplot(212)
    bottom.plot(x, per_phase.get("v_ucm") or [], color=theme.V_UCM,
                linewidth=1.5, label="V_UCM (task-irrelevant)")
    bottom.plot(x, per_phase.get("v_ort") or [], color=theme.V_ORT,
                linestyle="--", linewidth=1.5, label="V_ORT (task-relevant)")
    bottom.set_xlabel("Gait cycle (%)", fontsize=10)
    bottom.set_ylabel("Variance per DOF", fontsize=10)
    bottom.legend(fontsize=8)
    theme.style_axis(bottom)
    figure.tight_layout()
    return figure


def _build_not_available_page(title, reason=None):
    """A simple 'not available' text page for a curve with no reusable
    Figure (either shaped_results reported it unavailable, or no matching
    Figure was supplied) -- U5 Approach step 2's requirement that an
    unavailable section still produces a page instead of failing the whole
    export."""
    figure, axis = _new_text_page()
    text = f"{title}\n\nNot available"
    if reason:
        text += f"\n\nReason: {reason}"
    axis.text(0.05, 0.95, text, fontsize=12, va="top", ha="left", transform=axis.transAxes)
    return figure


# _format_metric_cell/_format_symmetry_cell were folded into
# report_formatting.py's format_metric_value/format_symmetry_value, shared
# with clinician_gui.py's on-screen metrics grid -- see _load_report_formatting
# above.


def _build_metrics_page(metrics):
    """Gait-metrics table page (U5 Approach step 2, third sub-item):
    renders shaped_results["metrics"] as a matplotlib table. A metric
    missing a leg's value, or with no symmetry figure, still gets a row --
    the cell reads its own already-shaped "not available"/reason text
    rather than raising."""
    metrics = metrics or {}
    figure, axis = _new_text_page()
    axis.set_title("Gait-cycle metrics", fontsize=14, pad=20)

    if not metrics:
        axis.text(0.05, 0.85, "No gait metrics available.", fontsize=12, transform=axis.transAxes)
        return figure

    columns = ["Metric", "Right", "Left", "Symmetry (R/L)"]
    rows = []
    for name, row in metrics.items():
        row = row or {}
        rows.append([
            str(name).replace("_", " "),
            # Wrapped, not truncated. A status string is prose ("no left gait
            # cycle segmented") and routinely outruns a column built for
            # "0.71 s"; matplotlib does not clip an over-wide cell, it draws
            # straight through the neighbour, so the text ended up sitting in
            # the Right column reading as that leg's value.
            _cell(_report_formatting.format_metric_value(row.get("r"))),
            _cell(_report_formatting.format_metric_value(row.get("l"))),
            _cell(_report_formatting.format_symmetry_value(row.get("symmetry"))),
        ])

    table = axis.table(cellText=rows, colLabels=columns, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    # Row height follows the tallest cell. A fixed 1.5 fitted one line, so a
    # wrapped two-line reason drew above and below its own row box -- the
    # overflow moved from sideways into the next column to vertically over the
    # row border, which is not a fix.
    tallest = max((cell.count("\n") + 1) for row in rows for cell in row)
    table.scale(1, 1.5 * tallest)
    return figure


def _build_confidence_page(confidence):
    """Confidence-summary page (U5 Approach step 2, fourth sub-item): one
    line per segment with its display tier/label, or the whole-trial
    "not available" banner text when shaped_results["confidence"]["available"]
    is False."""
    confidence = confidence or {}
    figure, axis = _new_text_page()
    axis.set_title("Confidence summary", fontsize=14, pad=20)

    if not confidence.get("available", False):
        banner = confidence.get("banner") or "Confidence indicator is not available for this recording."
        axis.text(0.05, 0.85, banner, fontsize=12, va="top", ha="left", wrap=True, transform=axis.transAxes)
        return figure

    segments = confidence.get("segments") or {}
    if not segments:
        axis.text(
            0.05, 0.85, "No per-segment confidence data available.", fontsize=12,
            transform=axis.transAxes,
        )
        return figure

    # One row per segment: a tier chip, the segment, its RMS, then the
    # accessibility sentence. Until 2026-09-04 this page rendered every tier
    # as identical black text, so the one thing a tier is for -- letting a
    # clinician find the doubtful segment without reading -- did not survive
    # the export. The GUI showed chips; the PDF a wall of prose.
    y = 0.88
    for segment_name, row in segments.items():
        row = row or {}
        tier = row.get("display_tier") or row.get("tier") or "not_scored"
        colours = theme.TIER.get(tier, theme.TIER["not_scored"])

        # Uppercase short tag, per DESIGN.md: the sentence-case treatment is
        # for the GUI's long in-panel labels, a standalone tag is uppercase.
        # The tag is also what keeps this readable in greyscale and to a
        # colourblind reader -- the colour is never the only carrier.
        axis.text(0.05, y, tier.replace("_", " ").upper(), fontsize=8,
                  family="monospace", va="center", ha="left", color=colours["fg"],
                  transform=axis.transAxes,
                  bbox={"facecolor": colours["bg"], "edgecolor": colours["fg"],
                        "linewidth": 0.6, "boxstyle": "round,pad=0.35"})

        axis.text(0.26, y, str(segment_name), fontsize=10, va="center",
                  ha="left", transform=axis.transAxes)

        rms = row.get("rms_deg")
        rms_display = (f"{rms:.1f} deg RMS" if isinstance(rms, (int, float))
                       else "not scored")
        axis.text(0.60, y, rms_display, fontsize=10, family="monospace",
                  va="center", ha="left", color=theme.INK_2,
                  transform=axis.transAxes)
        y -= 0.035

        label_text = row.get("label_text")
        if label_text:
            y = _wrapped_note(axis, 0.26, y + 0.008, label_text, width=74,
                              fontsize=8, line_height=0.016)
        y -= 0.022
    return figure


def export_report_to_pdf(pdf_path, shaped_results, figures=None):
    """Writes shaped_results (shape_results_for_display's output) to a
    single PDF at pdf_path via PdfPages (KTD2): a metadata title page, one
    page per curve in shaped_results["curves"] (reusing the matching
    Figure from `figures` when available -- never re-plotting), a
    gait-metrics table page, and a confidence-summary page.

    `figures` is a dict keyed by the same curve labels as
    shaped_results["curves"], mapping to the matplotlib Figure objects
    already built for on-screen display (e.g. ClinicianGUI's
    self._current_figures) -- or None/omitted for a curve with no Figure,
    in which case (or when shaped_results marks that curve unavailable) a
    simple "not available" text page is written instead.

    Pure w.r.t. Tk -- no tkinter import in this module. Never recomputes
    pipeline results; only consumes the already-shaped structure and
    already-built Figures passed in. Never raises on an unavailable
    section -- only on things like an unwritable pdf_path, which is a
    real failure the caller (ClinicianGUI's export handler) is expected to
    route through map_error_to_message.

    Returns {"pdf_path": str(pdf_path), "page_count": int} so a caller can
    build its own confirmation message (e.g. for messagebox.showinfo)
    without re-deriving the path or guessing the page count.
    """
    figures = figures or {}
    shaped_results = shaped_results or {}
    pages = []

    with PdfPages(pdf_path) as pdf:
        # Counted at the point of writing rather than by a `+= 1` beside each
        # call site. The three optional score pages below were added
        # 2026-09-01 under a single increment that already belonged to the
        # metadata page, so a six-page report reported three -- the count and
        # the writing had drifted apart because they were two separate
        # statements that had to be kept in step by hand.
        def save(figure):
            pdf.savefig(figure)
            pages.append(figure)

        save(_build_metadata_page(shaped_results.get("metadata")))

        # Second, so the headline numbers are found without paging through
        # every joint-angle curve to reach the metrics table.
        summary = shaped_results.get("summary_scores")
        summary_page = _build_summary_page(summary)
        if summary_page is not None:
            save(summary_page)
        for builder, payload in ((_build_gdi_figure, (summary or {}).get("gdi_detail")),
                                 (_build_synergy_figure, (summary or {}).get("synergy_detail"))):
            page = builder(payload)
            if page is not None:
                save(page)

        curves = shaped_results.get("curves") or {}
        for label, curve in curves.items():
            curve = curve or {}
            figure = figures.get(label)
            if curve.get("available") and figure is not None:
                save(figure)
            else:
                save(_build_not_available_page(f"Joint-angle curve: {label}", curve.get("reason")))

        save(_build_metrics_page(shaped_results.get("metrics")))
        save(_build_confidence_page(shaped_results.get("confidence")))

    return {"pdf_path": str(pdf_path), "page_count": len(pages)}
