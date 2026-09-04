"""One clinical PDF for a whole session, from every stride it contains.

Built 2026-09-01. The per-trial reports (`make_reports.py`) answer "what did
this trial look like". This answers "what does this participant look like",
and for the synergy index that is the only defensible question of the two.

**Why the synergy index belongs at session level.** UCM decomposes variance
*across strides*: it asks whether the joints co-vary from stride to stride in
a way that stabilises the task variable. A single trial here carries four to
six strides, which is a very thin basis for estimating a variance, let alone
splitting it into a 15-dimensional nullspace and a 3-dimensional complement.
Pooling a session gives 60-90 strides. The per-trial figure is still reported
as a within-trial diagnostic, but the session number is the one to quote.

**GDI is different and both levels are meaningful.** It scores a mean curve
against a normative reference, so it is well defined for a single trial. The
session report gives the pooled figure *and* the trial-by-trial breakdown,
because the spread across a session is itself diagnostic -- a monotonic slide
across trial order is a measurement problem rather than a gait finding, which
is exactly what `session_drift.py` exists to catch.

Reads the pooled `*_all-trials_*` matrices that `combine_curves` already
writes, and their `_index.csv` sidecars for the column-to-trial mapping, so
nothing is recomputed and the report cannot disagree with the per-trial ones.

Run with the OpenSim interpreter (`envs/opencap-processing`) -- the synergy
Jacobian needs a model.

Usage:
    python session_report.py --session data/xsens_sessions/XsensSession_AN \\
        [--reference context/gdi_reference_2026-08-27] [--conversion ik]
"""
import argparse
import importlib.util
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # no display on a batch run

import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

REPO_ROOT = Path(__file__).resolve().parent
PAGE_SIZE = (8.5, 11)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The shared palette. Loaded eagerly and by path, matching how this file
# reaches every other sibling. Until 2026-09-04 the four colours below were
# copied here from report_export.py rather than shared, so the two reports
# that quote the same GDI drew its normative band in two different greens.
theme = _load("_theme_for_session", "figure_theme.py")
_gdi_scoring = _load("_gdi_scoring_for_session", "gdi_scoring.py")


# The GDI half moved to gdi_scoring.py on 2026-09-04, so the clinician GUI
# can score a session without importing this file -- which would switch the
# GUI's process to Agg and silently disable the gait-event picker. Re-exported
# under their original names: cohort_scores.py, validate_control_baseline.py
# and this file's own tests all reach them through here.
pooled_paths = _gdi_scoring.pooled_paths
stride_trials = _gdi_scoring.stride_trials
gdi_by_trial = _gdi_scoring.gdi_by_trial


def session_scores(session_dir, reference_dir, conversion="ik",
                   feature_set=None, model_path=None):
    """GDI and the synergy index over every stride in the session."""
    gdi = _load("_gdi_for_session", "gdi.py")
    curves = _load("_curves_for_session", "curve_features.py")
    scores_mod = _load("_scores_for_session", "trial_scores.py")

    feature_set = gdi.get_feature_set(feature_set or gdi.DEFAULT_FEATURE_SET)
    scored = _gdi_scoring.score_pooled_gdi(session_dir, reference_dir,
                                           conversion, feature_set,
                                           gdi=gdi, curves=curves)
    paths = pooled_paths(session_dir, conversion)

    result = {"session": Path(session_dir).name, "conversion": conversion,
              "feature_set": feature_set.name,
              "gdi": scored["gdi"], "by_trial": scored["by_trial"]}

    result["synergy"] = {}
    if model_path:
        # Over every pooled stride: this is the whole point of doing it at
        # session level rather than per trial.
        #
        # Keyed by side, matching `gdi` above. GDI is a per-limb score by
        # definition, and while this was a single unkeyed value a cohort-level
        # GDI-vs-synergy comparison could pair a left GDI with a right synergy
        # index with nothing downstream able to tell. The previous code read
        # `paths.get("right") or next(iter(paths.values()))`, so a session
        # without a right side scored whichever limb happened to come first
        # and labelled it nothing.
        for side, entry in paths.items():
            result["synergy"][side] = scores_mod.synergy_for_trial(
                str(entry["matrix"]), model_path)
    return result


def _text_page():
    figure = Figure(figsize=PAGE_SIZE, dpi=100)
    axis = figure.add_subplot(111)
    axis.axis("off")
    return figure, axis


def _title_page(scores):
    figure, axis = _text_page()
    gdi = scores["gdi"]
    strides = sum(v["n_strides"] for k, v in gdi.items() if isinstance(v, dict))
    trials = max((len(t) for t in scores["by_trial"].values()), default=0)

    axis.text(0.05, 0.95, "Session Report", fontsize=20, fontweight="bold",
              va="top", transform=axis.transAxes)
    lines = [
        f"Session:        {scores['session']}",
        f"Conversion:     {scores['conversion']}",
        f"Trials pooled:  {trials}",
        f"Strides pooled: {strides}",
        f"Feature set:    {scores['feature_set']}",
    ]
    axis.text(0.05, 0.86, "\n".join(lines), fontsize=12, va="top",
              family="monospace", transform=axis.transAxes)
    axis.text(
        0.05, 0.62,
        "The synergy index on this report is computed across every stride in "
        "the session, not per trial. Uncontrolled-manifold analysis decomposes "
        "variance ACROSS strides, and a single trial of four to six strides is "
        "too thin a basis to split into a 15-dimensional nullspace and a "
        "3-dimensional complement. The per-trial reports carry a within-trial "
        "figure for diagnostic use; this is the one to quote.",
        fontsize=10, va="top", style="italic", wrap=True,
        transform=axis.transAxes)
    return figure


def _gdi_trend_figure(scores):
    """GDI per trial in session order -- the plot that shows a drift.

    Trial order should not predict a score. Every trial is converted,
    calibrated and segmented independently, so a monotonic slide across this
    axis is something moving in the recording rather than in the participant.
    """
    by_trial = scores.get("by_trial") or {}
    if not by_trial:
        return None
    figure = Figure(figsize=PAGE_SIZE, dpi=100)
    axis = figure.add_subplot(211)
    band = theme.NORMATIVE_BAND[0]
    axis.axhspan(band["low"], band["high"], color=band["color"], alpha=0.6,
                 zorder=0)
    axis.axhline(100, color=theme.NORMATIVE_MEAN_LINE, linewidth=1.1, zorder=1)

    for side in ("right", "left"):
        series = by_trial.get(side)
        if not series:
            continue
        # Colour, linestyle and marker all carry the limb -- see figure_theme
        # on why hue alone is not allowed to.
        style = theme.limb_style(side)
        colour = style["color"]
        values = list(series.values())
        axis.plot(range(1, len(values) + 1), values, color=colour,
                  linestyle=style["linestyle"], marker=style["marker"],
                  label=side, markersize=5)
        # A perfectly flat series has zero variance, so corrcoef divides by
        # zero and returns nan -- which would print "r=nan" on a clinical
        # report. A flat series has no trend, which is a real answer.
        if len(values) > 2 and np.ptp(values) > 0:
            order = np.arange(1, len(values) + 1)
            r = float(np.corrcoef(order, values)[0, 1])
            axis.plot(order, np.poly1d(np.polyfit(order, values, 1))(order),
                      "--", color=colour, alpha=0.5,
                      label=f"{side} trend r={r:+.2f}")
        elif len(values) > 2:
            axis.plot([], [], " ", label=f"{side} trend r=0.00 (flat)")

    axis.set_xlabel("Trial (session order)", fontsize=10)
    axis.set_ylabel("GDI", fontsize=10)
    axis.set_title("GDI across the session", fontsize=13, pad=12)
    axis.legend(fontsize=8)
    theme.style_axis(axis)
    axis.text(0.01, -0.42,
              "Trial order should not predict a score: trials are processed "
              "independently, so a monotonic trend here indicates drift in the "
              "recording rather than a change in the participant.",
              transform=axis.transAxes, fontsize=8, style="italic", wrap=True,
              va="top")
    figure.tight_layout()
    return figure


def build_report(scores, pdf_path, export=None):
    export = export or _load("_export_for_session", "report_export.py")
    scores_mod = _load("_scores_fmt_for_session", "trial_scores.py")
    # The summary page shows one synergy figure, so the report has to choose a
    # limb -- but it must say which. Preferring right keeps the existing
    # reports comparable; naming it is what stops a reader pairing it with the
    # other limb's GDI, which is the whole reason this is keyed by side.
    synergy_by_side = scores.get("synergy") or {}
    synergy_side = "right" if "right" in synergy_by_side else next(
        iter(sorted(synergy_by_side)), None)
    synergy = synergy_by_side.get(synergy_side)

    summary = scores_mod.summary_for_report(scores["gdi"], synergy,
                                            side=synergy_side)

    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(str(pdf_path)) as pdf:
        pdf.savefig(_title_page(scores))
        page = export._build_summary_page(summary)
        if page is not None:
            pdf.savefig(page)
        for builder, payload in ((export._build_gdi_figure, scores["gdi"]),
                                 (_gdi_trend_figure, scores),
                                 (export._build_synergy_figure, synergy)):
            page = builder(payload)
            if page is not None:
                pdf.savefig(page)
    return pdf_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--session", required=True, action="append",
                        dest="sessions")
    parser.add_argument("--reference", default="context/gdi_reference_2026-08-27")
    parser.add_argument("--conversion", default="ik")
    parser.add_argument("--feature-set", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    failed = 0
    for session in args.sessions:
        model_dir = Path(session) / "OpenSimData" / "Model"
        models = [p for p in sorted(model_dir.glob("*.osim"))
                  if not p.stem.endswith("_calibrated")]
        try:
            scores = session_scores(session, args.reference, args.conversion,
                                    args.feature_set,
                                    str(models[0]) if models else None)
            out = Path(args.out) if args.out else \
                Path(session) / "Reports" / f"{Path(session).name}_session_{args.conversion}.pdf"
            path = build_report(scores, out)
            gdi = scores["gdi"]
            print(f"{Path(session).name}: "
                  f"R {gdi.get('right', {}).get('mean', float('nan')):.1f} / "
                  f"L {gdi.get('left', {}).get('mean', float('nan')):.1f}  "
                  f"-> {path}", flush=True)
        except BaseException as exc:  # noqa: BLE001 -- one session must not end the run
            failed += 1
            print(f"{Path(session).name}: FAILED -- {type(exc).__name__}: {exc}",
                  flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
