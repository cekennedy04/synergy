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
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

PAGE_SIZE = (8.5, 11)  # inches -- US Letter, matches PdfPages' own default assumption of one Figure per page.


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


def _format_metric_cell(entry):
    if not entry or not entry.get("available"):
        status = (entry or {}).get("status")
        return status or "not available"
    value = entry.get("value")
    units = entry.get("units") or ""
    if isinstance(value, (int, float)):
        return f"{value:.2f} {units}".strip()
    return f"{value} {units}".strip()


def _format_symmetry_cell(entry):
    if not entry or not entry.get("available"):
        reason = (entry or {}).get("reason")
        return reason or "not available"
    value = entry.get("value")
    units = entry.get("units") or ""
    if isinstance(value, (int, float)):
        return f"{value:.1f} {units}".strip()
    return f"{value} {units}".strip()


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
            _format_metric_cell(row.get("r")),
            _format_metric_cell(row.get("l")),
            _format_symmetry_cell(row.get("symmetry")),
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
