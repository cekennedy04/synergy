"""Render every figure this project shows a clinician, so someone can look at it.

Built 2026-09-04, after three defects shipped past a green test suite and were
found only by opening the output:

  - The GDI legend sat in the lower right. On a GDI axis low means impaired,
    so the legend was covering the strides of the worst limb in the trial --
    the one the report was opened to look at. Every assertion about that
    figure passed; the data was in the artist, just underneath a white box.
  - The GDI basis line ran off the right edge of the page, taking with it the
    sentence saying the score covers the whole session rather than this
    trial. `wrap=True` measures against the figure, not the axes.
  - The picker drew its background traces in matplotlib's default cycle, so a
    C1 orange curve appeared on the right leg's own panel -- orange being the
    colour that means "left limb" everywhere else in the project.

None of those are assertable without deciding in advance to assert them, and
nobody decides to assert "the legend is not on top of the data". They are all
obvious in about two seconds of looking. The barrier to looking was that
producing the pictures took a throwaway script each time, so this is that
script, kept.

**The fixtures are chosen to provoke, not to flatter.** This is the part worth
preserving. A gallery rendered from tidy symmetric data shows nothing: the
legend collision only appeared because one limb was impaired and its strides
sat low on the axis, and the truncation only appeared because the basis
string had grown long enough to reach the margin. So the fixtures here carry
an impaired limb, a long note, an unavailable section and a trial whose
events cluster at one end. If a case ever renders badly in the wild, add it
here rather than fixing it in place -- the gallery is the regression record
for things tests cannot hold.

Usage:
    ~/miniconda3/python.exe render_gallery.py [--out DIR] [--open]

Runs on base python: no opensim, no tkinter, no display. Output defaults to
context/render-gallery/, which is gitignored.

Not covered here: cohort_figures.py's six figures, which need a scored cohort
rather than a fixture, and session_report.py's own pages, which need a pooled
session. Both live behind real data in context/. Render those by running
their own CLIs when you touch them.
"""
import argparse
import importlib.util
import math
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # rendering to files is the whole job

REPO_ROOT = Path(__file__).resolve().parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fixtures. Awkward on purpose -- see the module docstring.
# ---------------------------------------------------------------------------

def _impaired_gdi():
    """One limb inside the band, one well below it.

    The asymmetry is the point. Two healthy limbs both plot mid-axis, where
    nothing overlaps and every layout looks fine.
    """
    return {
        "right": {"mean": 88.0, "sd": 1.2, "n_strides": 4,
                  "per_stride": [86.4, 88.1, 89.5, 88.0]},
        "left": {"mean": 78.2, "sd": 1.4, "n_strides": 4,
                 # 76.0 is the one the legend used to cover.
                 "per_stride": [76.0, 79.4, 78.2, 79.1]},
        "feature_set": "reduced6",
    }


def _long_basis():
    """As long as the real one, which is what reached the margin."""
    return ("reduced6 feature set. 100 is the control mean; each 10 points is "
            "one standard deviation below it. Scored over all 42 strides "
            "pooled across this session so far, not this trial alone -- it "
            "moves as further trials are processed.")


def _summary_scores():
    gdi = _impaired_gdi()
    return {
        "gdi": {"right_display": "88.0  (SD 1.2 over 4 strides)",
                "left_display": "78.2  (SD 1.4 over 4 strides)",
                "basis": _long_basis()},
        "gdi_detail": gdi,
        "synergy_note": ("The synergy index is not reported here. It "
                         "decomposes variance across strides, and a session "
                         "is the smallest defensible basis for it -- run "
                         "session_report.py for that number."),
    }


def _synergy_detail():
    """A trial that is negative through single support.

    A curve that is positive throughout hides whether the zero line and the
    two fills are distinguishable at all.
    """
    delta_v = [0.42, 0.51, 0.33, 0.05, -0.18, -0.27, -0.11, 0.19, 0.38, 0.47]
    return {"task_variable": "pelvis-relative CoM",
            "per_phase": {"delta_v": delta_v,
                          "v_ucm": [1.2, 1.3, 1.15, 0.95, 0.82, 0.78, 0.9,
                                    1.05, 1.25, 1.35],
                          "v_ort": [0.78, 0.79, 0.82, 0.9, 1.0, 1.05, 1.01,
                                    0.86, 0.87, 0.88]}}


def _curve(available=True):
    x = list(range(101))
    mean = [22.0 * math.sin(2 * math.pi * i / 100.0) - 4.0 for i in x]
    if not available:
        return {"available": False,
                "reason": "knee_angle_l is absent from the .mot file."}
    return {"available": True, "x": x, "mean": mean,
            "sd": [3.0 + 1.5 * math.cos(2 * math.pi * i / 100.0) for i in x]}


def _picker_motion():
    """A trial whose walking sits at one end, with a flat lead-in.

    Real captures start with the subject standing still, and a legend pinned
    to a fixed corner lands on the peaks an operator is trying to click. A
    uniform sine wave would never show that.
    """
    n = 420

    class _Motion:
        n_rows = n
        name = "gallery_trial_03"
        signals = {
            "r_calc": [0.0] * 90 + [math.sin(2 * math.pi * (i / 68.0))
                                    for i in range(n - 90)],
            "r_toe": [0.0] * 90 + [0.8 * math.sin(2 * math.pi * (i / 68.0) + 0.9)
                                   for i in range(n - 90)],
            "l_calc": [0.0] * 90 + [math.sin(2 * math.pi * (i / 68.0) + math.pi)
                                    for i in range(n - 90)],
            "l_toe": [0.0] * 90 + [0.8 * math.sin(2 * math.pi * (i / 68.0)
                                                  + math.pi + 0.9)
                                   for i in range(n - 90)],
        }

        def time_at(self, frame):
            return frame / 60.0

    return _Motion()


# ---------------------------------------------------------------------------
# The surfaces.
# ---------------------------------------------------------------------------

def render_all(out_dir):
    """Write every surface to `out_dir`. Returns the paths written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    def save(figure, name, page_size=True):
        path = out_dir / f"{name}.png"
        # Saved WITHOUT bbox_inches="tight". Tight cropping resizes the canvas
        # and re-wraps the text, so it hides exactly the margin overruns this
        # gallery exists to catch -- the basis-line truncation was invisible
        # in a tight-cropped render and obvious at true page size.
        figure.savefig(path, dpi=100)
        written.append(path)
        return path

    export = _load("_export_for_gallery", "report_export.py")
    gui = _load("_gui_for_gallery", "clinician_gui.py")

    # -- the PDF report, page by page ------------------------------------
    save(export._build_metadata_page({
        "subject_session_id": "XsensSession_AN", "trial_name": "trial_03",
        "date": "2026-09-04", "duration_display": "12.4 s",
        "sensor_coverage": "17 of 17 segments", "translation_type": "pinned",
        "gait_speed_method": "stance-phase foot velocity",
        "spatial_displacement_validated": False,
    }), "report_1_metadata")

    save(export._build_summary_page(_summary_scores()), "report_2_summary")
    save(export._build_summary_page({
        "unavailable": ("No normative GDI reference at "
                        "context/gdi_reference_2026-08-27. GDI is scored "
                        "against a control cohort, so without it there is no "
                        "scale to report a number on."),
    }), "report_2_summary_unavailable")

    save(export._build_gdi_figure(_impaired_gdi()), "report_3_gdi")
    save(export._build_synergy_figure(_synergy_detail()), "report_4_synergy")

    def _metric(value, units):
        return {"available": True, "value": value, "units": units}

    # A row with a missing leg and a row with no symmetry figure are both in
    # here: an all-populated table never shows how the "not available" text
    # sits against real numbers in the same column.
    save(export._build_metrics_page({
        "stride_length_m": {"r": _metric(1.21, "m"), "l": _metric(0.94, "m"),
                            "symmetry": {"available": True, "value": 77.7,
                                         "units": "% (R/L)"}},
        "cadence_steps_per_min": {"r": _metric(108.4, "steps/min"),
                                  "l": _metric(108.4, "steps/min"),
                                  "symmetry": {"available": True,
                                               "value": 100.0,
                                               "units": "% (R/L)"}},
        "gait_speed_m_s": {"r": _metric(1.09, "m/s"), "l": _metric(1.09, "m/s"),
                           "symmetry": {"available": False,
                                        "reason": "inferred, not measured"}},
        "stance_time_s": {"r": _metric(0.71, "s"),
                          "l": {"available": False,
                                "status": "no left gait cycle segmented"},
                          "symmetry": None},
    }), "report_5_metrics")

    save(export._build_confidence_page({
        "available": True,
        "segments": {"pelvis": {"label_text": "High agreement", "rms_deg": 2.1},
                     "femur_r": {"label_text": "Medium agreement", "rms_deg": 6.8},
                     "tibia_l": {"label_text": "Low agreement", "rms_deg": 14.3},
                     "calcn_l": {"label_text": "Not scored", "rms_deg": None}},
    }), "report_6_confidence")
    save(export._build_not_available_page(
        "Joint-angle curve: knee_angle_l",
        "knee_angle_l is absent from the .mot file."), "report_7_unavailable")

    # -- the on-screen curve, which the PDF reuses verbatim ---------------
    save(gui.build_curve_figure(_curve()), "gui_curve")

    # -- the gait-event picker -------------------------------------------
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    if REPO_ROOT_STR not in sys.path:
        sys.path.insert(0, REPO_ROOT_STR)
    picker_mod = _load("gait_event_picker_ui", "gait_event_picker_ui.py")
    picker_data = _load("gait_event_picker", "gait_event_picker.py")

    picker = picker_data.GaitEventPicker(_picker_motion())
    for frame in (118, 188, 258, 328):
        picker.mark("rHS", frame)
    for frame in (153, 223, 293):
        picker.mark("rTO", frame)
    for frame in (153, 223, 293, 363):
        picker.mark("lHS", frame)
    for frame in (188, 258, 328):
        picker.mark("lTO", frame)

    figure = Figure(figsize=(13, 7.5), dpi=100)
    FigureCanvasAgg(figure)
    picker_mod.build_picker_view(
        picker_mod.EventPickerModel(picker), figure)
    save(figure, "picker_window")

    return written


REPO_ROOT_STR = str(REPO_ROOT)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(REPO_ROOT / "context"
                                             / "render-gallery"),
                        help="where to write the PNGs (default: "
                             "context/render-gallery, which is gitignored)")
    parser.add_argument("--open", dest="open_after", action="store_true",
                        help="open the folder when done (Windows/macOS)")
    args = parser.parse_args(argv)

    written = render_all(args.out)
    for path in written:
        print(path)
    print(f"\n{len(written)} surfaces -> {args.out}")
    print("Now look at them. What to look for is in "
          ".claude/skills/render-and-look/SKILL.md")

    if args.open_after:
        target = os.path.abspath(args.out)
        if sys.platform == "win32":
            os.startfile(target)                       # noqa: S606
        elif sys.platform == "darwin":
            os.system(f'open "{target}"')              # noqa: S605
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
