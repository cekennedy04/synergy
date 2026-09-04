#!/usr/bin/env python
r"""Recover one trial the clinician GUI could not segment, by hand.

Built 2026-09-03. The picker (`gait_event_picker_ui.py`) is the backup plan
for automatic gait-event detection, and until now it was a backup plan the
product's own users could not reach: the clinician GUI runs Xsens `.mvnx`
sessions, while the only wired picker path -- `Examples/gaitAnalysis-UCM.py`'s
`run_interactive` -- downloads OpenCap sessions. A clinician whose trial
failed detection was told to "try a longer or cleaner recording" and had no
way to rescue a recording that was very often fine.

Usage, from the repo root:

    python launch_gui.py --help        # if unsure which interpreter you have
    python rescue_trial.py --session <session folder> --trial <trial name>

Add `--route xtoo` if the GUI ran that route, and `--report out.pdf` to write
the same PDF the GUI's Export button writes. Needs the `opencap-processing`
interpreter, like every other stage of this pipeline.

**Why this is a separate process rather than a button in the GUI.** Measured
2026-09-03. The GUI runs its pipeline on a background daemon thread
(`start_pipeline_thread`) and talks to Tk through a queue drained by
`root.after`. Opening a matplotlib window from that thread deadlocks: the
worker never returns, and matplotlib warns "Starting a Matplotlib GUI outside
of the main thread will likely fail" on the way in. Reaching the picker from
the GUI would take a cross-thread modal handshake that puts a blocking window
in the middle of a clinician's Run, for a minority of trials, with a hang as
the failure mode. A clear error message naming this tool is a better trade
than a possible hang, so `clinician_gui.map_error_to_message` names it and the
GUI's own pipeline stays unattended.

**It re-enters at the gait stage, and that is the point.** Conversion --
orientations, IMUPlacer, IK, marker export -- is the expensive part, and the
GUI already did it before detection failed, so the `.mot` and `.trc` are
sitting on disk. Re-running only `_run_gait_stages` means a rescued trial
produces exactly the artefacts a successful run would have: the same gait
metrics, the same per-trial curve matrix, the same pooled session matrix, the
same PDF. Nothing here re-implements a pipeline stage; if it did, the two
copies would drift and a rescued trial would stop being comparable to a
normal one.

**Never import an Agg-forcing module here.** `make_reports.py`,
`make_comparison_figures.py`, `session_report.py` and `cohort_figures.py` all
call `matplotlib.use("Agg")` at import, process-wide. Under Agg the picker's
window never opens and `plt.show()` returns immediately, which
`segment_walking` would read as the operator declining. That is the exact trap
`make_manual_event_provider` raises about, and a recovery tool that imported
one of those would disable the thing it exists to run. A test pins it.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


class TrialNotConvertedError(RuntimeError):
    """The trial's converted outputs are not on disk, so there is nothing to
    re-analyse. Raised with the missing file named, because the alternative is
    an OpenSim failure several stages later about a file handle."""


def _load_xsens():
    sys.path.insert(0, str(REPO_ROOT))
    import xsens_to_opensim
    return xsens_to_opensim


def _load_gui():
    """clinician_gui, imported for its pipeline stages only.

    Importing it builds no widgets -- every Tk call is inside `ClinicianGUI`
    or `main()` -- and it does not force a matplotlib backend, so the picker
    can still open a window in this process.
    """
    sys.path.insert(0, str(REPO_ROOT))
    import clinician_gui
    return clinician_gui


def converted_outputs(session_dir, trial_name, xsens_module=None):
    """The paths a previous GUI run left behind, or a refusal naming what is
    missing.

    Returns (paths, mot_path). `paths` is exactly what
    `resolve_session_output_paths` returns, so `_run_gait_stages` receives the
    same structure the GUI hands it rather than a reconstruction.
    """
    xsens = xsens_module if xsens_module is not None else _load_xsens()
    paths = xsens.resolve_session_output_paths(session_dir, trial_name)
    mot_path = str(Path(paths["results_dir"]) / paths["output_motion_filename"])

    for label, candidate in (("motion", mot_path), ("marker", paths["trc_path"])):
        if not Path(candidate).is_file():
            raise TrialNotConvertedError(
                "this trial's converted %s file is not on disk:\n    %s\n"
                "Nothing here re-runs the conversion -- it re-analyses what "
                "the conversion already produced. Run the trial through the "
                "clinician GUI (clinician_gui.py, via launch_gui.py) first; "
                "if it failed at gait-event detection, the conversion "
                "succeeded and these files will be there."
                % (label, candidate))

    return paths, mot_path


def rescue(session_dir, trial_name, conversion="ik", show=None,
           xsens_module=None, gui_module=None, progress=None,
           **stage_modules):
    """Re-run the gait stages for one already-converted trial, with the picker.

    `show` is injected so a test can drive the whole path without a display;
    it defaults to the real window.

    The provider is wrapped in `reuse_across_legs` before it goes anywhere.
    `_run_gait_stages` constructs `gait_analysis` twice -- once per leg -- and
    a trial that failed auto-trim failed for both, so an unwrapped provider
    would open two windows for one trial and accept two answers that need not
    agree.
    """
    from gait_event_picker_ui import (make_manual_event_provider,
                                      reuse_across_legs)

    gui = gui_module if gui_module is not None else _load_gui()
    paths, mot_path = converted_outputs(session_dir, trial_name,
                                        xsens_module=xsens_module)

    report = progress if progress is not None else (lambda message: None)
    provider = reuse_across_legs(make_manual_event_provider(show=show))

    return gui._run_gait_stages(
        session_dir, None, trial_name, paths, mot_path, conversion,
        stage_modules.get("gait_fixed_module"),
        stage_modules.get("foot_progression_module"),
        stage_modules.get("combine_module"),
        report,
        manual_event_provider=provider,
    )


def write_report(result, pdf_path, gui_module=None, report_module=None):
    """The same PDF the GUI's Export button writes, built headlessly.

    `shape_results_for_display` and `build_curve_figure` are both documented
    Tk-free, and `report_export` imports no tkinter, so the whole report is
    reachable from a terminal. Reused rather than re-implemented: a rescued
    trial's report has to be the same document as a normal one's.
    """
    gui = gui_module if gui_module is not None else _load_gui()
    if report_module is None:
        sys.path.insert(0, str(REPO_ROOT))
        import report_export as report_module

    shaped = gui.shape_results_for_display(result)
    figures = {label: gui.build_curve_figure(curve)
               for label, curve in (shaped.get("curves") or {}).items()}
    return report_module.export_report_to_pdf(pdf_path, shaped, figures)


def _summarise(result):
    """What the operator reads when the rescue works: the metrics, and where
    the files went. Deliberately plain text -- this is a terminal tool."""
    lines = ["", "Recovered %s." % result.get("trial_name", "the trial")]
    for side in ("r", "l"):
        analysis = result.get("gait_" + side)
        events = getattr(analysis, "gaitEvents", None) or {}
        cycles = events.get("ipsilateralIdx")
        lines.append("  %s leg: %s gait cycle(s)"
                     % ("right" if side == "r" else "left",
                        len(cycles) if cycles is not None else "unknown"))
    for label, key in (("per-trial curves (right)", "curves_matrix_r_path"),
                       ("per-trial curves (left)", "curves_matrix_l_path"),
                       ("pooled matrix (right)", "combined_matrix_r_path"),
                       ("pooled matrix (left)", "combined_matrix_l_path")):
        if result.get(key):
            lines.append("  %s: %s" % (label, result[key]))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=("Recover one trial whose automatic gait-event detection "
                     "failed, by picking heel strikes and toe-offs by hand. "
                     "Re-analyses the conversion the clinician GUI already "
                     "produced; it does not re-run the conversion."))
    parser.add_argument("--session", required=True,
                        help="the session folder the GUI processed")
    parser.add_argument("--trial", required=True,
                        help="the trial name, without an extension")
    parser.add_argument("--route", default="ik", choices=("ik", "xtoo"),
                        help="the conversion route the GUI used (default: ik). "
                             "The two write differently-named curve files and "
                             "must not be pooled together.")
    parser.add_argument("--report", metavar="PDF",
                        help="also write the clinician report to this path")
    args = parser.parse_args(argv)

    try:
        result = rescue(args.session, args.trial, conversion=args.route,
                        progress=lambda message: print(message))
    except TrialNotConvertedError as exc:
        print("Cannot rescue this trial: %s" % exc, file=sys.stderr)
        return 2

    print(_summarise(result))

    if args.report:
        written = write_report(result, args.report)
        print("  report: %s (%d pages)"
              % (written["pdf_path"], written["page_count"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
