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

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

PAGE_SIZE = (8.5, 11)  # inches -- US Letter, matches PdfPages' own default assumption of one Figure per page.

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_MODULE_LOADING_PATH = os.path.join(_REPO_ROOT, "module_loading.py")
_REPORT_FORMATTING_PATH = os.path.join(_REPO_ROOT, "report_formatting.py")


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


_report_formatting = _bootstrap_load_module_loading().load_module_by_path(
    "report_formatting_for_report_export", _REPORT_FORMATTING_PATH
)


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
        axis.text(
            0.05, 0.32, "Note: this pipeline's inverse kinematics solves orientations only, with root translation pinned. Gait speed and stride length are therefore inferred from stance-phase foot velocity rather than measured from global displacement, and are not independent of one another. Cadence is derived from event timing and is unaffected.",
            fontsize=9, va="top", ha="left", style="italic", wrap=True,
            transform=axis.transAxes,
        )
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
    if not gdi and not synergy:
        return None

    figure, axis = _new_text_page()
    axis.text(0.05, 0.95, "Summary scores", fontsize=18, fontweight="bold",
              va="top", ha="left", transform=axis.transAxes)

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
        axis.text(0.08, y, gdi.get("basis", ""), fontsize=9, style="italic",
                  va="top", transform=axis.transAxes)
        y -= 0.09

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
            axis.text(0.08, y, line, fontsize=9, style="italic", va="top",
                      wrap=True, transform=axis.transAxes)
            y -= 0.035
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

    axis.axhspan(90, 110, color="#cfe6cf", alpha=0.7, zorder=0,
                 label="within 1 SD of control mean")
    axis.axhspan(80, 90, color="#f2e3c2", alpha=0.7, zorder=0,
                 label="1-2 SD below")
    axis.axhline(100, color="#4a7c4a", linewidth=1.2, zorder=1)

    for position, (name, entry) in enumerate(sides):
        if not entry:
            continue
        strides = entry.get("per_stride") or []
        if strides:
            axis.plot([position] * len(strides), strides, "o", color="#666666",
                      markersize=5, alpha=0.65, zorder=2,
                      label="individual strides" if position == 0 else None)
        axis.plot([position], [entry["mean"]], "D", color="#1f6fb4",
                  markersize=11, zorder=3,
                  label="trial mean" if position == 0 else None)
        axis.annotate(f"{entry['mean']:.1f}", (position, entry["mean"]),
                      textcoords="offset points", xytext=(16, -4), fontsize=12,
                      fontweight="bold", color="#1f6fb4")

    axis.set_xticks([0, 1])
    axis.set_xticklabels(["Right", "Left"], fontsize=12)
    axis.set_xlim(-0.5, 1.5)
    axis.set_ylabel("Gait Deviation Index", fontsize=11)
    axis.set_title("GDI against the normative range", fontsize=14, pad=14)
    axis.grid(axis="y", alpha=0.25)
    axis.legend(loc="lower right", fontsize=8, framealpha=0.9)
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
    top.axhline(0, color="#888888", linewidth=1)
    top.plot(x, delta_v, color="#1f6fb4", linewidth=1.8)
    top.fill_between(x, 0, delta_v, where=[v > 0 for v in delta_v],
                     color="#1f6fb4", alpha=0.20, interpolate=True)
    top.fill_between(x, 0, delta_v, where=[v <= 0 for v in delta_v],
                     color="#d95f02", alpha=0.20, interpolate=True)
    top.set_ylabel("dV", fontsize=10)
    top.set_title(f"Synergy across the gait cycle -- {synergy.get('task_variable', '')}",
                  fontsize=13, pad=12)
    top.grid(alpha=0.25)
    top.text(0.01, 0.95, "above zero: joints co-vary to stabilise the task",
             transform=top.transAxes, fontsize=8, va="top", style="italic")

    bottom = figure.add_subplot(212)
    bottom.plot(x, per_phase.get("v_ucm") or [], color="#2e8b57",
                linewidth=1.5, label="V_UCM (task-irrelevant)")
    bottom.plot(x, per_phase.get("v_ort") or [], color="#d95f02",
                linewidth=1.5, label="V_ORT (task-relevant)")
    bottom.set_xlabel("Gait cycle (%)", fontsize=10)
    bottom.set_ylabel("Variance per DOF", fontsize=10)
    bottom.legend(fontsize=8)
    bottom.grid(alpha=0.25)
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
            _report_formatting.format_metric_value(row.get("r")),
            _report_formatting.format_metric_value(row.get("l")),
            _report_formatting.format_symmetry_value(row.get("symmetry")),
        ])

    table = axis.table(cellText=rows, colLabels=columns, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)
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

    lines = []
    for segment_name, row in segments.items():
        row = row or {}
        rms = row.get("rms_deg")
        rms_display = f"{rms:.1f} deg RMS" if isinstance(rms, (int, float)) else "not scored"
        label_text = row.get("label_text") or "not scored"
        lines.append(f"{segment_name}: {label_text} ({rms_display})")

    axis.text(
        0.05, 0.85, "\n".join(lines), fontsize=11, va="top", ha="left", transform=axis.transAxes,
    )
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
    page_count = 0

    with PdfPages(pdf_path) as pdf:
        pdf.savefig(_build_metadata_page(shaped_results.get("metadata")))

        # Second, so the headline numbers are found without paging through
        # every joint-angle curve to reach the metrics table.
        summary = shaped_results.get("summary_scores")
        summary_page = _build_summary_page(summary)
        if summary_page is not None:
            pdf.savefig(summary_page)
        for builder, payload in ((_build_gdi_figure, (summary or {}).get("gdi_detail")),
                                 (_build_synergy_figure, (summary or {}).get("synergy_detail"))):
            page = builder(payload)
            if page is not None:
                pdf.savefig(page)
        page_count += 1

        curves = shaped_results.get("curves") or {}
        for label, curve in curves.items():
            curve = curve or {}
            figure = figures.get(label)
            if curve.get("available") and figure is not None:
                pdf.savefig(figure)
            else:
                pdf.savefig(_build_not_available_page(f"Joint-angle curve: {label}", curve.get("reason")))
            page_count += 1

        pdf.savefig(_build_metrics_page(shaped_results.get("metrics")))
        page_count += 1

        pdf.savefig(_build_confidence_page(shaped_results.get("confidence")))
        page_count += 1

    return {"pdf_path": str(pdf_path), "page_count": page_count}
