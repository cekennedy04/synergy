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
import csv
import importlib.util
import re
from collections import OrderedDict
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


def pooled_paths(session_dir, conversion="ik"):
    """The session's pooled matrix per side, and its index sidecar."""
    curves = Path(session_dir) / "GaitCurves"
    found = {}
    for side in ("right", "left"):
        matches = sorted(curves.glob(f"*_all-trials_{conversion}_{side}.csv"))
        matches = [m for m in matches if not m.name.endswith("_index.csv")]
        if matches:
            index = matches[0].with_name(matches[0].stem + "_index.csv")
            found[side] = {"matrix": matches[0],
                           "index": index if index.is_file() else None}
    if not found:
        raise FileNotFoundError(
            f"no pooled '_all-trials_{conversion}_' matrix in {curves}. Run the "
            "session through process_participants first -- pooling happens at "
            "the end of a batch, not per trial.")
    return found


def stride_trials(index_path):
    """Column index -> trial name, from the provenance sidecar."""
    if not index_path or not Path(index_path).is_file():
        return []
    with open(index_path, newline="", encoding="utf-8") as handle:
        return [row["trial"] for row in csv.DictReader(handle)]


def gdi_by_trial(per_stride, trials):
    """Mean GDI per trial, in session order.

    Ordered by trial number rather than by first appearance, so the x-axis of
    the trend plot is session order -- which is the axis a drift shows up on.
    """
    grouped = OrderedDict()
    for score, trial in zip(per_stride, trials):
        grouped.setdefault(trial, []).append(score)

    def trial_number(name):
        found = re.findall(r"(\d+)", name)
        return int(found[-1]) if found else 0

    return OrderedDict(
        (name, float(np.mean(grouped[name])))
        for name in sorted(grouped, key=trial_number))


def session_scores(session_dir, reference_dir, conversion="ik",
                   feature_set=None, model_path=None):
    """GDI and the synergy index over every stride in the session."""
    gdi = _load("_gdi_for_session", "gdi.py")
    curves = _load("_curves_for_session", "curve_features.py")
    scores_mod = _load("_scores_for_session", "trial_scores.py")

    feature_set = gdi.get_feature_set(feature_set or gdi.DEFAULT_FEATURE_SET)
    reference = gdi.load_gdi_reference(reference_dir, feature_set)
    row_order = curves.exported_row_order()
    paths = pooled_paths(session_dir, conversion)

    result = {"session": Path(session_dir).name, "conversion": conversion,
              "feature_set": feature_set.name, "gdi": {}, "by_trial": {}}

    for side, entry in paths.items():
        matrix = curves.load_curve_matrix(entry["matrix"], row_order)
        per_stride = curves.score_curves(matrix, side, reference, feature_set,
                                         gdi, row_order)
        result["gdi"][side] = {
            "mean": float(np.mean(per_stride)),
            "sd": float(np.std(per_stride)) if per_stride.size > 1 else None,
            "n_strides": int(per_stride.size),
            "per_stride": [float(v) for v in per_stride],
        }
        trials = stride_trials(entry["index"])
        if len(trials) == per_stride.size:
            result["by_trial"][side] = gdi_by_trial(per_stride, trials)
    result["gdi"]["feature_set"] = feature_set.name

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
    axis.axhspan(90, 110, color="#cfe6cf", alpha=0.6, zorder=0)
    axis.axhline(100, color="#4a7c4a", linewidth=1.1, zorder=1)

    for side, colour in (("right", "#1f6fb4"), ("left", "#d95f02")):
        series = by_trial.get(side)
        if not series:
            continue
        values = list(series.values())
        axis.plot(range(1, len(values) + 1), values, "o-", color=colour,
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
    axis.grid(alpha=0.25)
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
