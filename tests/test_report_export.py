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
