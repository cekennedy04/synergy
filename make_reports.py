"""Write a clinical PDF report for every trial in a processed session.

Built 2026-08-31. The batch path produces `.mot`, `.trc`, curve matrices and
pooled session matrices, but no PDF -- `export_report_to_pdf` consumes
`shape_results_for_display`'s output, which needs the live `gait_analysis`
objects, and those cannot cross the process boundary the batch isolates each
trial behind. So the reports are a separate pass.

**It re-runs the pipeline in process, deliberately.** The alternative is
reconstructing a shaped result from files on disk, which would mean a second
implementation of what `shape_results_for_display` already does and a second
thing to keep in step with it. Re-running costs about a minute per trial and
cannot drift from the batch's own numbers.

**Figures are built, not skipped.** `export_report_to_pdf` accepts
`figures=None` and writes "not available" pages instead of plots, which
produces a PDF that looks complete and contains nothing worth reading.
`clinician_gui.build_curve_figure` is Tk-free, so the real figures are
available headlessly; matplotlib is forced to the Agg backend so no display
is needed.

Run with the OpenSim interpreter (`envs/opencap-processing`).

Usage:
    python make_reports.py --session data/xsens_sessions/XsensSession_AN \\
        --mvnx-dir "context/Data for Alex/AN/HD Reprocessed" [--out DIR]
"""
import argparse
import os
import re
from pathlib import Path

# Before anything imports pyplot: there is no display on a batch run, and the
# default backend would try to open one.
import matplotlib
matplotlib.use("Agg")


def trial_mvnx_files(mvnx_dir):
    """The session's .mvnx in natural trial order."""
    paths = sorted(Path(mvnx_dir).glob("*.mvnx"),
                   key=lambda p: [int(t) if t.isdigit() else t.lower()
                                  for t in re.split(r"(\d+)", p.stem)])
    if not paths:
        raise FileNotFoundError(f"no .mvnx files in {mvnx_dir}")
    return paths


def report_path(out_dir, session_dir, trial_name, conversion):
    """Named by trial AND route: ik and xtoo produce different numbers for the
    same trial, and one silently overwriting the other would leave a report
    whose contents do not match its filename."""
    return Path(out_dir) / f"{Path(session_dir).name}-{conversion}-{trial_name}.pdf"


def build_figures(gui, shaped):
    """A Figure per curve, keyed as export_report_to_pdf expects.

    A curve the shaping marked unavailable gets no figure rather than an empty
    one -- the exporter already writes an honest "not available" page for it.
    """
    figures = {}
    for label, curve in (shaped.get("curves") or {}).items():
        if not curve or not curve.get("available", True):
            continue
        try:
            figure = gui.build_curve_figure(curve)
            # build_curve_figure returns None for an unavailable curve; a None
            # in the dict would reach the exporter as a Figure and fail there.
            if figure is not None:
                figures[label] = figure
        except Exception:
            # A figure that will not build must not cost the whole report;
            # the exporter degrades to a text page for this curve alone.
            continue
    return figures


def add_scores(shaped, result, session_dir, reference_dir, scores=None):
    """Fold GDI and the synergy index into the metrics the report renders.

    Injected into `shaped["metrics"]` rather than given their own page: the
    metrics table already renders whatever it is handed, so this needs no
    change to report_export and cannot drift from its formatting.

    Failures are swallowed per score, not per report. A missing GDI reference
    or an unavailable model should cost that row, not the whole PDF -- and an
    absent row is honest, where a zero would be indistinguishable from a
    computed result.
    """
    scores = scores or _load_scores()
    metrics = shaped.setdefault("metrics", {})

    gdi_scores = synergy = None
    try:
        gdi_scores = scores.gdi_for_curves(
            {"right": result.get("curves_matrix_r_path"),
             "left": result.get("curves_matrix_l_path")}, reference_dir)
    except Exception:
        gdi_scores = None
    try:
        right = result.get("curves_matrix_r_path")
        if right:
            synergy = scores.synergy_for_trial(right, result["model_file"])
    except Exception:
        synergy = None

    metrics.update(scores.format_for_report(gdi_scores, synergy))
    # Right by construction: `synergy` above is computed from
    # curves_matrix_r_path or not at all. Saying so keeps the report from
    # inviting a pairing with the left GDI printed beside it.
    shaped["summary_scores"] = scores.summary_for_report(
        gdi_scores, synergy, side="right" if synergy else None)
    return shaped


def _load_scores():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_trial_scores_for_reports", Path(__file__).resolve().parent / "trial_scores.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_report(gui, report_export, session_dir, mvnx_path, out_dir,
                conversion="ik", overwrite=False, reference_dir=None):
    """One trial -> one PDF. Returns the path, or None if skipped."""
    trial_name = Path(mvnx_path).stem
    destination = report_path(out_dir, session_dir, trial_name, conversion)
    if destination.exists() and not overwrite:
        return None

    result = gui.run_pipeline(str(session_dir), str(mvnx_path),
                              conversion=conversion,
                              combine_module=gui._NO_COMBINE)
    shaped = gui.shape_results_for_display(result)
    if reference_dir:
        add_scores(shaped, result, session_dir, reference_dir)
    figures = build_figures(gui, shaped)
    destination.parent.mkdir(parents=True, exist_ok=True)
    report_export.export_report_to_pdf(str(destination), shaped, figures)

    import matplotlib.pyplot as plt
    for figure in figures.values():
        plt.close(figure)          # 90 trials x several figures exhausts memory
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--session", required=True)
    parser.add_argument("--mvnx-dir", required=True)
    parser.add_argument("--out", default=None,
                        help="Default: <session>/Reports")
    parser.add_argument("--conversion", default="ik", choices=("ik", "xtoo"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--trial", action="append", dest="only")
    parser.add_argument("--gdi-reference", default="context/gdi_reference_2026-08-27",
                        help="Directory holding the GDI reference pair; the "
                             "GDI and synergy rows are omitted without it.")
    args = parser.parse_args(argv)

    import clinician_gui as gui
    report_export = gui._load_report_export() if hasattr(gui, "_load_report_export") \
        else __import__("report_export")

    out_dir = Path(args.out) if args.out else Path(args.session) / "Reports"
    written, skipped, failed = [], [], []

    for path in trial_mvnx_files(args.mvnx_dir):
        if args.only and path.stem not in set(args.only):
            continue
        try:
            destination = make_report(gui, report_export, args.session, path,
                                      out_dir, args.conversion, args.overwrite,
                                      reference_dir=args.gdi_reference)
            (written if destination else skipped).append(path.stem)
            print(f"  {path.stem}: {'written' if destination else 'exists, skipped'}",
                  flush=True)
        except BaseException as exc:  # noqa: BLE001 -- one trial must not end the run
            failed.append((path.stem, f"{type(exc).__name__}: {exc}"))
            print(f"  {path.stem}: FAILED -- {type(exc).__name__}: {exc}", flush=True)

    print(f"\n{len(written)} written, {len(skipped)} already present, "
          f"{len(failed)} failed -> {out_dir}")
    for name, error in failed:
        print(f"  {name}: {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
