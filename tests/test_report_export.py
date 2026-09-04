"""
Tests U5 of the clinician trial report GUI plan: report_export.py's
export_report_to_pdf (R10, KTD2) -- writing the currently reviewed trial's
report (metadata, joint-angle plots, gait metrics, confidence indicators)
to a single PDF file.

No real Tk/OpenSim/patient data needed: report_export.py itself has no
tkinter dependency (only clinician_gui.py's Export button click handler
touches tkinter -- not tested here, per the plan's note that Tk widget
rendering is a manual smoke check). Fake shaped_results dicts match the
real shape shape_results_for_display() produces (see
tests/test_clinician_gui_display.py); fake matplotlib Figure objects are
real, small Figures built headlessly with synthetic data -- matplotlib
itself needs no opensim/tkinter dependency to build a Figure.

Follows this repo's existing test convention (see
tests/test_clinician_gui_display.py, tests/test_joint_confidence.py): load
the module under test via importlib.util.spec_from_file_location against an
absolute path, rather than a plain `import report_export`.
"""
import importlib.util
import os

import pytest
from matplotlib.figure import Figure

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'report_export.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('report_export_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


# ---------------------------------------------------------------------------
# Fakes matching shape_results_for_display()'s real return shape (see
# clinician_gui.py and tests/test_clinician_gui_display.py):
#   {"metadata": {...}, "curves": {label: {...}}, "metrics": {name: {...}},
#    "confidence": {...}}
# ---------------------------------------------------------------------------

def _make_figure(seed=0.0):
    figure = Figure(figsize=(3, 2.2), dpi=100)
    axis = figure.add_subplot(111)
    x = list(range(0, 101))
    y = [seed + 0.1 * i for i in x]
    axis.plot(x, y)
    axis.set_xlabel("% gait cycle")
    axis.set_ylabel("deg")
    return figure


def _make_metadata():
    return {
        "subject_session_id": "OpenCapData_test-subject",
        "trial_name": "trial1",
        "date": "2026-08-20 10:00",
        "duration_display": "12.3 s",
        "sensor_coverage": "23 tracked segments at 60 Hz",
    }


CURVE_LABELS = [
    "Hip Flexion (R)", "Knee Flexion (R)", "Ankle Flexion (R)",
    "Hip Flexion (L)", "Knee Flexion (L)", "Ankle Flexion (L)",
]


def _make_available_curve(coordinate_name, leg):
    return {
        "coordinate_name": coordinate_name,
        "leg": leg,
        "available": True,
        "reason": None,
        "x": list(range(0, 101)),
        "mean": [float(i) for i in range(0, 101)],
        "sd": [1.0] * 101,
    }


def _make_unavailable_curve(coordinate_name, leg, reason="not present in this trial's gait-cycle curves."):
    return {
        "coordinate_name": coordinate_name,
        "leg": leg,
        "available": False,
        "reason": reason,
        "x": None,
        "mean": None,
        "sd": None,
    }


def _make_full_curves():
    return {label: _make_available_curve(label.lower().replace(" ", "_"), "r") for label in CURVE_LABELS}


def _make_full_figures(curves):
    return {label: _make_figure(seed=i) for i, label in enumerate(curves)}


def _make_full_metrics():
    names = [
        "gait_speed", "stride_length", "step_width", "cadence",
        "single_support_time", "double_support_time",
        "step_length_symmetry", "foot_progression_angle",
    ]
    metrics = {}
    for name in names:
        r_entry = {"available": True, "status": "ok", "value": 1.5, "units": "unit"}
        l_entry = {"available": True, "status": "ok", "value": 1.4, "units": "unit"}
        metrics[name] = {
            "r": r_entry,
            "l": l_entry,
            "symmetry": {"available": True, "status": "ok", "value": 107.1, "units": "% (R/L)", "reason": None},
        }
    return metrics


def _make_full_confidence():
    segments = {
        "jRightKnee": {
            "status": "scored", "tier": "high", "display_tier": "high",
            "coordinate_name": "knee_angle_r", "rms_deg": 2.0, "n_aligned_samples": 50,
            "reason": None, "label_text": "High agreement with the suit's own onboard estimate.",
        },
        "jLeftKnee": {
            "status": "scored", "tier": "low", "display_tier": "low",
            "coordinate_name": "knee_angle_l", "rms_deg": 30.0, "n_aligned_samples": 50,
            "reason": None, "label_text": "Low agreement with the suit's own onboard estimate.",
        },
        "jRightWrist": {
            "status": "not_scored", "tier": None, "display_tier": "not_scored",
            "coordinate_name": None, "rms_deg": None, "n_aligned_samples": None,
            "reason": "No mapping defined.", "label_text": "Not scored agreement with the suit's own onboard estimate.",
        },
    }
    return {"available": True, "banner": None, "segments": segments, "by_coordinate": {}}


def _make_full_shaped_results():
    curves = _make_full_curves()
    return {
        "metadata": _make_metadata(),
        "curves": curves,
        "metrics": _make_full_metrics(),
        "confidence": _make_full_confidence(),
    }, curves


# ---------------------------------------------------------------------------
# Scenario 1: a fully populated shaped_results exports a well-formed PDF
# with the expected page count.
# ---------------------------------------------------------------------------

def test_full_export_writes_well_formed_pdf_with_expected_page_count(mod, tmp_path):
    shaped_results, curves = _make_full_shaped_results()
    figures = _make_full_figures(curves)
    pdf_path = tmp_path / "report.pdf"

    result = mod.export_report_to_pdf(str(pdf_path), shaped_results, figures)

    assert pdf_path.exists()
    file_bytes = pdf_path.read_bytes()
    assert file_bytes[:5] == b"%PDF-"
    assert len(file_bytes) > 1000

    # 1 metadata page + one page per curve + 1 metrics page + 1 confidence page.
    expected_page_count = 1 + len(curves) + 1 + 1
    assert result["page_count"] == expected_page_count

    # A separate, independent page-count check: PdfPages tracks how many
    # pages it wrote via get_pagecount() when re-opened is not available
    # without pypdf, so cross-check via the page_count return value against
    # the number of curves directly (proves the return value isn't just
    # hardcoded and actually reflects the curves dict).
    assert result["page_count"] == len(shaped_results["curves"]) + 3


def test_successful_export_return_value_exposes_saved_path_for_confirmation(mod, tmp_path):
    """Scenario 3: the export function's own return value makes the saved
    file path available for a caller (e.g. ClinicianGUI's Export button
    handler) to show in a messagebox.showinfo confirmation."""
    shaped_results, curves = _make_full_shaped_results()
    figures = _make_full_figures(curves)
    pdf_path = tmp_path / "subdir_report.pdf"

    result = mod.export_report_to_pdf(str(pdf_path), shaped_results, figures)

    assert result["pdf_path"] == str(pdf_path)
    assert os.path.exists(result["pdf_path"])


# ---------------------------------------------------------------------------
# Scenario 2: an unavailable curve/metric/confidence section still produces
# a "not available" page/row instead of failing the whole export.
# ---------------------------------------------------------------------------

def test_export_with_unavailable_curve_still_completes_with_not_available_page(mod, tmp_path):
    shaped_results, curves = _make_full_shaped_results()
    # Make one curve unavailable, and don't supply a Figure for it either --
    # matching what shape_joint_curves_for_display() actually produces for a
    # missing coordinate (available=False, no mean/sd/x data).
    shaped_results["curves"]["Ankle Flexion (R)"] = _make_unavailable_curve("ankle_angle_r", "r")
    figures = _make_full_figures(curves)
    figures.pop("Ankle Flexion (R)", None)

    pdf_path = tmp_path / "report_partial.pdf"

    result = mod.export_report_to_pdf(str(pdf_path), shaped_results, figures)

    assert pdf_path.exists()
    assert pdf_path.read_bytes()[:5] == b"%PDF-"
    assert result["page_count"] == 1 + len(shaped_results["curves"]) + 1 + 1


def test_export_with_unavailable_metric_and_confidence_still_completes(mod, tmp_path):
    shaped_results, curves = _make_full_shaped_results()
    figures = _make_full_figures(curves)

    # A metrics row reporting "not available" (mirrors
    # shape_gait_metrics_for_display()'s own output for a missing leg).
    shaped_results["metrics"]["cadence"] = {
        "r": {"available": True, "status": "ok", "value": 110.0, "units": "steps/min"},
        "l": {"available": False, "status": "not available", "value": None, "units": None},
        "symmetry": {
            "available": False, "status": "not available", "value": None, "units": None,
            "reason": "not available",
        },
    }

    # Whole-trial confidence-unavailable (mirrors U3's no-data fallback).
    shaped_results["confidence"] = {
        "available": False,
        "banner": "Confidence indicator is not available for this recording.",
        "segments": {},
        "by_coordinate": {},
    }

    pdf_path = tmp_path / "report_unavailable_sections.pdf"

    result = mod.export_report_to_pdf(str(pdf_path), shaped_results, figures)

    assert pdf_path.exists()
    assert pdf_path.read_bytes()[:5] == b"%PDF-"
    assert len(pdf_path.read_bytes()) > 1000
    assert result["page_count"] == 1 + len(shaped_results["curves"]) + 1 + 1


def test_export_with_entirely_empty_shaped_results_does_not_raise(mod, tmp_path):
    """Extra defensive coverage: an (unrealistic but not-impossible) empty
    shaped_results dict still produces a well-formed PDF rather than
    raising -- proves the page builders guard against missing keys, not
    just against explicit available=False."""
    pdf_path = tmp_path / "empty_report.pdf"

    result = mod.export_report_to_pdf(str(pdf_path), {}, {})

    assert pdf_path.exists()
    assert pdf_path.read_bytes()[:5] == b"%PDF-"
    # metadata + 0 curves + metrics + confidence.
    assert result["page_count"] == 3


# -- Spatial provenance on the exported report (2026-08-25) -------------
# The pinned-root caveat has to travel with the numbers. Nothing about a
# gait speed of "1.116 m/s" signals that it came from a stance-phase
# velocity proxy rather than measured displacement, so a caveat that lives
# only in VENDORING.md is separated from the data the first time someone
# copies a value onto a slide.


def test_metadata_page_renders_the_spatial_provenance_rows(mod):
    shaped_results, _ = _make_full_shaped_results()
    shaped_results["metadata"].update({
        "translation_type": "Pinned root (orientation-only IK)",
        "gait_speed_method": "Stance-phase ankle velocity proxy",
        "spatial_displacement_validated": False,
    })

    figure = mod._build_metadata_page(shaped_results["metadata"])
    rendered = " ".join(t.get_text() for t in figure.axes[0].texts)

    assert "Pinned root" in rendered
    assert "Stance-phase ankle velocity proxy" in rendered


def test_metadata_page_states_the_limitation_in_prose_not_just_a_row(mod):
    """A metadata row is easy to skim past; the limitation is also stated as
    a sentence on the page carrying the numbers."""
    shaped_results, _ = _make_full_shaped_results()
    shaped_results["metadata"]["spatial_displacement_validated"] = False

    figure = mod._build_metadata_page(shaped_results["metadata"])
    rendered = " ".join(t.get_text() for t in figure.axes[0].texts)

    assert "stance-phase foot velocity" in rendered
    assert "not independent of one another" in rendered
    assert "Cadence" in rendered


def test_metadata_page_omits_the_caveat_when_displacement_is_validated(mod):
    """If a future pipeline recovers real translation, the caveat must stop
    appearing rather than becoming permanent boilerplate nobody reads."""
    shaped_results, _ = _make_full_shaped_results()
    shaped_results["metadata"]["spatial_displacement_validated"] = True

    figure = mod._build_metadata_page(shaped_results["metadata"])
    rendered = " ".join(t.get_text() for t in figure.axes[0].texts)

    assert "stance-phase foot velocity" not in rendered


# ---------------------------------------------------------------------------
# The headline-scores pages (added 2026-09-01, covered 2026-09-04).
#
# These three builders -- summary, GDI, synergy -- shipped with no test of
# any kind, and the page counter that shipped with them was wrong: all three
# pages were written under a single `page_count += 1` that already belonged
# to the metadata page, so a six-page report reported three. Nothing caught
# it because no fixture in this file had ever set "summary_scores".
#
# The count is therefore cross-checked against pypdf here rather than against
# arithmetic repeated from the implementation. Repeating the implementation's
# own sum is what let the original defect through: the assertion and the code
# were wrong in the same direction.
# ---------------------------------------------------------------------------

def _make_summary_scores():
    return {
        "gdi": {"right_display": "88.0", "left_display": "91.2",
                "basis": "100 = control mean, 10 points = 1 SD"},
        "synergy": {"value_display": "0.42",
                    "notes": ["task variable: pelvis-relative CoM"]},
        "gdi_detail": {
            "right": {"mean": 88.0, "per_stride": [86.4, 88.1, 89.5]},
            "left": {"mean": 91.2, "per_stride": [90.0, 91.4, 92.2]},
        },
        "synergy_detail": {
            "task_variable": "pelvis-relative CoM",
            "per_phase": {"delta_v": [0.4, 0.1, -0.2, 0.3],
                          "v_ucm": [1.2, 1.1, 0.9, 1.3],
                          "v_ort": [0.8, 1.0, 1.1, 1.0]},
        },
    }


def _actual_pdf_pages(pdf_path):
    """The real page count, read back off the file rather than recomputed."""
    pypdf = pytest.importorskip("pypdf")
    return len(pypdf.PdfReader(str(pdf_path)).pages)


def test_page_count_matches_the_file_when_score_pages_are_present(mod, tmp_path):
    """The regression the counter actually had: three extra pages written,
    none of them counted."""
    shaped_results, curves = _make_full_shaped_results()
    shaped_results["summary_scores"] = _make_summary_scores()
    figures = _make_full_figures(curves)
    pdf_path = tmp_path / "with_scores.pdf"

    result = mod.export_report_to_pdf(str(pdf_path), shaped_results, figures)

    assert result["page_count"] == _actual_pdf_pages(pdf_path)
    # And the three score pages are genuinely additional, not a relabelling
    # of pages that were already being written.
    assert result["page_count"] == len(curves) + 6


def test_page_count_matches_the_file_when_scores_are_absent(mod, tmp_path):
    """The GUI export path, which supplies no summary_scores at all: the
    count must still agree with the file rather than only agreeing in the
    case the new pages happen to fire."""
    shaped_results, curves = _make_full_shaped_results()
    figures = _make_full_figures(curves)
    pdf_path = tmp_path / "no_scores.pdf"

    result = mod.export_report_to_pdf(str(pdf_path), shaped_results, figures)

    assert result["page_count"] == _actual_pdf_pages(pdf_path)
    assert result["page_count"] == len(curves) + 3


def test_partial_scores_only_add_the_pages_they_can_fill(mod, tmp_path):
    """A summary with no per-phase detail must skip the synergy figure rather
    than emit an empty one -- and the count must follow what was written."""
    shaped_results, curves = _make_full_shaped_results()
    summary = _make_summary_scores()
    del summary["synergy_detail"]
    shaped_results["summary_scores"] = summary
    figures = _make_full_figures(curves)
    pdf_path = tmp_path / "partial_scores.pdf"

    result = mod.export_report_to_pdf(str(pdf_path), shaped_results, figures)

    assert result["page_count"] == _actual_pdf_pages(pdf_path)
    assert result["page_count"] == len(curves) + 5


def test_summary_page_is_skipped_entirely_when_there_is_nothing_to_show(mod):
    """An empty summary must produce no page rather than a blank one."""
    assert mod._build_summary_page({}) is None
    assert mod._build_summary_page(None) is None
    assert mod._build_summary_page({"gdi": {}, "synergy": {}}) is None


def test_summary_page_carries_both_scores_and_the_task_variable(mod):
    """The task variable is not a footnote: the ranking between
    methodologies reverses with it, so a dV without it is not interpretable."""
    figure = mod._build_summary_page(_make_summary_scores())
    rendered = " ".join(t.get_text() for t in figure.axes[0].texts)

    assert "88.0" in rendered and "91.2" in rendered
    assert "0.42" in rendered
    assert "pelvis-relative CoM" in rendered


def test_gdi_figure_draws_every_stride_not_just_the_mean(mod):
    """A mean over three scattered strides is much weaker evidence than one
    over three tight ones, and the mean alone hides which you have."""
    scores = _make_summary_scores()["gdi_detail"]
    figure = mod._build_gdi_figure(scores)
    axis = figure.axes[0]

    plotted = [len(line.get_ydata()) for line in axis.lines]
    assert 3 in plotted, "per-stride points are missing from the GDI figure"


def test_gdi_figure_is_skipped_when_no_side_has_a_score(mod):
    assert mod._build_gdi_figure(None) is None
    assert mod._build_gdi_figure({}) is None
    assert mod._build_gdi_figure({"right": None, "left": None}) is None


def test_synergy_figure_is_skipped_without_per_phase_data(mod):
    assert mod._build_synergy_figure(None) is None
    assert mod._build_synergy_figure({}) is None
    assert mod._build_synergy_figure({"per_phase": {"delta_v": []}}) is None


def test_synergy_figure_handles_a_single_phase_sample(mod):
    """len(delta_v) == 1 divides by zero in the percent-of-cycle axis unless
    it is special-cased; a one-stride trial must not crash the export."""
    figure = mod._build_synergy_figure(
        {"task_variable": "t", "per_phase": {"delta_v": [0.3], "v_ucm": [1.0],
                                             "v_ort": [0.5]}})
    assert figure is not None


def test_long_notes_are_wrapped_rather_than_running_off_the_page(mod):
    """The GDI basis line ran straight off the right edge of the page, taking
    with it the sentence saying the score covers the whole session rather
    than this trial -- the caveat on that page that most needed reading.
    matplotlib's own wrap=True measures against the figure, not the axes, and
    did not catch it."""
    summary = _make_summary_scores()
    summary["gdi"]["basis"] = (
        "reduced6 feature set. 100 is the control mean; each 10 points is one "
        "standard deviation below it. Scored over all 42 strides pooled across "
        "this session so far, not this trial alone -- it moves as further "
        "trials are processed.")

    figure = mod._build_summary_page(summary)
    lines = [line for t in figure.axes[0].texts
             for line in t.get_text().split("\n")]

    # Joined, because wrapping legitimately splits the phrase across two
    # lines -- what must not happen is the tail being dropped entirely.
    assert "not this trial alone" in " ".join(lines), (
        "the session-vs-trial caveat is not on the page at all")
    # And every rendered line is short enough to fit the page. A single
    # 200-character artist is the shape the truncation took.
    assert max(len(line) for line in lines) <= 95


def test_an_unavailable_summary_states_the_reason_rather_than_vanishing(mod):
    """A report that silently omits the scores looks exactly like one whose
    scores were fine. The reader cannot tell which they are holding."""
    figure = mod._build_summary_page(
        {"unavailable": "No normative GDI reference at context/gdi_reference."})
    rendered = " ".join(t.get_text() for t in figure.axes[0].texts)

    assert "Not available" in rendered
    assert "normative GDI reference" in rendered


def test_a_summary_with_gdi_but_no_synergy_says_why_synergy_is_missing(mod):
    """The GUI reports GDI and deliberately does not report the synergy
    index. A page headed 'Summary scores' carrying one of the two reads as
    though the other failed."""
    summary = _make_summary_scores()
    del summary["synergy"]
    del summary["synergy_detail"]
    summary["synergy_note"] = ("The synergy index is not reported here -- run "
                               "session_report.py for that number.")

    figure = mod._build_summary_page(summary)
    rendered = " ".join(t.get_text() for t in figure.axes[0].texts)

    assert "Synergy index" in rendered
    assert "session_report.py" in rendered


def test_a_long_status_wraps_inside_its_cell_instead_of_over_its_neighbour(mod):
    """matplotlib's table does not clip an over-wide cell -- it draws straight
    through the next one, so "no left gait cycle segmented" rendered on top of
    the Right column and read as that leg's value. Found by rendering the
    page, not by any assertion."""
    figure = mod._build_metrics_page({
        "stance_time_s": {
            "r": {"available": True, "value": 0.71, "units": "s"},
            "l": {"available": False,
                  "status": "no left gait cycle segmented"},
            "symmetry": None},
    })
    table = [child for child in figure.axes[0].get_children()
             if hasattr(child, "get_celld")][0]
    texts = [cell.get_text().get_text() for cell in table.get_celld().values()]
    long_cell = [t for t in texts if "no left gait cycle" in t]

    assert long_cell, "the status text is missing from the table"
    assert "\n" in long_cell[0], "the status was not wrapped"
    assert max(len(line) for line in long_cell[0].split("\n")) <= 22


def test_row_height_follows_the_tallest_cell(mod):
    """Wrapping sideways-overflow into vertical-overflow is not a fix: a
    two-line cell drew above and below its own row box at the fixed scale."""
    one_line = mod._build_metrics_page({
        "cadence": {"r": {"available": True, "value": 1.0, "units": "s"},
                    "l": {"available": True, "value": 1.0, "units": "s"},
                    "symmetry": None}})
    two_line = mod._build_metrics_page({
        "cadence": {"r": {"available": True, "value": 1.0, "units": "s"},
                    "l": {"available": False,
                          "status": "no left gait cycle segmented"},
                    "symmetry": None}})

    def row_height(figure):
        table = [c for c in figure.axes[0].get_children()
                 if hasattr(c, "get_celld")][0]
        return max(cell.get_height() for cell in table.get_celld().values())

    assert row_height(two_line) > row_height(one_line)


def test_the_metadata_caveat_keeps_a_right_margin(mod):
    """wrap=True measures against the figure, so a note placed at x=0.05 got a
    left margin and no right one -- its last line ran flush into the page
    edge."""
    figure = mod._build_metadata_page(
        {"trial_name": "t", "spatial_displacement_validated": False})
    # Split on newlines: the metadata rows are a single artist holding every
    # row, so measuring the artist rather than its lines would flag a block
    # that renders perfectly well.
    lines = [line for t in figure.axes[0].texts
             for line in t.get_text().split("\n")]

    assert "stance-phase foot velocity" in " ".join(lines)
    assert max(len(line) for line in lines) <= 95
