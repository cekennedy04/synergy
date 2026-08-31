"""Detect measurement drift across a session's trials.

Built 2026-08-30, after scoring the first fully processed participant showed
its right-leg GDI falling monotonically across fifteen trials (r = -0.917)
while the left leg did not. That is not something gait does; it is something
sensors do, and nothing in the pipeline would have surfaced it.

**Why trial order is the axis.** Every trial is converted, calibrated and
segmented independently, so nothing carries between them inside the pipeline.
A quantity that nevertheless moves monotonically with trial number is moving
in the *recording*, not the analysis. That makes trial order the one axis on
which a drift is separable from ordinary between-trial variation.

**Asymmetry is what makes a drift diagnostic.** Fatigue, a loosening pelvis
strap, or global heading drift move both legs together. One side moving alone
points at that side's sensors. The report therefore always gives both legs,
never a single pooled number -- pooling is exactly what hides this.

**A trend is evidence of a problem, not of its cause.** Measured on the first
two participants: both showed a right-leg decline at r = -0.92 and -0.96, and
they had *different* causes -- one a right foot diverging from the pelvis in
yaw, feeding `fpa`; the other driven by `hip_flexion` with no foot yaw drift
at all. So this module reports which variables move and leaves the mechanism
to a human. Do not let it conclude anything.

Usage:
    python session_drift.py --session data/xsens_sessions/XsensSession_AN \\
        --reference context/gdi_reference_2026-08-27 [--conversion ik]
"""
import argparse
import importlib.util
import re
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent

# Below this, a trend is not worth a human's attention: between-trial variation
# alone produces moderate correlations on short sessions. Chosen to sit well
# under the |r| = 0.92 and 0.96 that motivated this, and above the |r| ~ 0.5
# seen on legs with no apparent problem.
TREND_ALERT_R = 0.8

# A correlation over three or four trials is not evidence of anything.
MIN_TRIALS_FOR_TREND = 6


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trial_curve_files(session_dir, side, conversion="ik"):
    """This session's per-trial curve exports for one side, in trial order.

    Pooled `*_all-trials_*` matrices are excluded deliberately: they are the
    concatenation this module exists to look inside.
    """
    curves = Path(session_dir) / "GaitCurves"
    if not curves.is_dir():
        raise FileNotFoundError(
            f"{curves} does not exist; this session has not been processed.")
    found = []
    for path in sorted(curves.glob(f"*-{conversion}-*_{side}.csv")):
        if "all-trials" in path.name:
            continue
        match = re.search(r"-(\d+)_%s\.csv$" % side, path.name)
        if match:
            found.append((int(match.group(1)), path))
    return [path for _number, path in sorted(found)], [n for n, _p in sorted(found)]


def linear_trend(order, values):
    """(r, slope, first-three mean, last-three mean) against trial order."""
    order = np.asarray(order, dtype=float)
    values = np.asarray(values, dtype=float)
    if values.size < 2 or np.ptp(values) == 0 or np.ptp(order) == 0:
        return 0.0, 0.0, float(values.mean()), float(values.mean())
    correlation = float(np.corrcoef(order, values)[0, 1])
    slope = float(np.polyfit(order, values, 1)[0])
    return (correlation, slope,
            float(values[:3].mean()), float(values[-3:].mean()))


def session_report(session_dir, reference, feature_set=None, conversion="ik",
                   gdi=None, curves=None):
    """Per-side GDI trend and per-variable trend for one session."""
    gdi = gdi or _load("_gdi_for_drift", "gdi.py")
    curves = curves or _load("_curves_for_drift", "curve_features.py")
    feature_set = gdi.get_feature_set(
        feature_set or reference.get("feature_set", gdi.DEFAULT_FEATURE_SET))
    row_order = curves.exported_row_order()
    variables = [t.replace("_{side}", "") for t in feature_set.features]

    report = {"session": Path(session_dir).name, "conversion": conversion,
              "feature_set": feature_set.name, "sides": {}}

    for side in ("right", "left"):
        files, numbers = trial_curve_files(session_dir, side, conversion)
        if len(files) < MIN_TRIALS_FOR_TREND:
            report["sides"][side] = {
                "n_trials": len(files),
                "note": (f"{len(files)} trials is too few for a trend; "
                         f"{MIN_TRIALS_FOR_TREND} are needed."),
            }
            continue

        scores, per_variable = [], {name: [] for name in variables}
        for path in files:
            matrix = curves.load_curve_matrix(path, row_order)
            scores.append(float(curves.score_curves(
                matrix, side, reference, feature_set, gdi, row_order).mean()))
            vectors = curves.to_feature_vectors(matrix, side, feature_set, gdi,
                                                row_order)
            for index, name in enumerate(variables):
                block = vectors[index * gdi.GDI_N_POINTS:
                                (index + 1) * gdi.GDI_N_POINTS, :]
                per_variable[name].append(float(block.mean()))

        r, slope, first, last = linear_trend(numbers, scores)
        report["sides"][side] = {
            "n_trials": len(files),
            "gdi": {"r": r, "slope": slope, "first3": first, "last3": last,
                    "alert": abs(r) >= TREND_ALERT_R},
            "variables": {
                name: dict(zip(("r", "slope", "first3", "last3"),
                               linear_trend(numbers, values)))
                for name, values in per_variable.items()
            },
        }
    return report


def alerts(report):
    """Sides whose GDI trend crosses the threshold, worst first."""
    found = []
    for side, data in report.get("sides", {}).items():
        gdi_trend = data.get("gdi")
        if gdi_trend and gdi_trend["alert"]:
            worst = max(data["variables"].items(),
                        key=lambda item: abs(item[1]["r"]))
            found.append({
                "side": side, "r": gdi_trend["r"],
                "change": gdi_trend["last3"] - gdi_trend["first3"],
                "leading_variable": worst[0], "variable_r": worst[1]["r"],
                "variable_change": worst[1]["last3"] - worst[1]["first3"],
            })
    return sorted(found, key=lambda item: -abs(item["r"]))


def format_report(report):
    lines = [f"{report['session']}  [{report['feature_set']}, "
             f"{report['conversion']}]"]
    for side, data in report["sides"].items():
        if "note" in data:
            lines.append(f"  {side:<6} {data['note']}")
            continue
        g = data["gdi"]
        flag = "  <-- ALERT" if g["alert"] else ""
        lines.append(f"  {side:<6} {data['n_trials']:2d} trials   "
                     f"GDI r={g['r']:+.3f}  {g['first3']:.1f} -> "
                     f"{g['last3']:.1f}{flag}")
        for name, trend in sorted(data["variables"].items(),
                                  key=lambda item: -abs(item[1]["r"])):
            mark = " *" if abs(trend["r"]) >= TREND_ALERT_R else ""
            lines.append(f"       {name:<16} r={trend['r']:+.3f}  "
                         f"{trend['last3'] - trend['first3']:+7.2f}{mark}")
    found = alerts(report)
    if found:
        lines.append("")
        for alert in found:
            lines.append(
                f"  {alert['side']} GDI moves {alert['change']:+.1f} points "
                f"across the session (r={alert['r']:+.3f}); largest variable "
                f"movement is {alert['leading_variable']} "
                f"({alert['variable_change']:+.2f} deg). A trend indicates a "
                "problem, not its cause -- check the raw recording before "
                "concluding anything."
            )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--session", required=True, action="append",
                        dest="sessions")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--feature-set", default=None)
    parser.add_argument("--conversion", default="ik")
    args = parser.parse_args(argv)

    gdi = _load("_gdi_for_drift_main", "gdi.py")
    feature_set = gdi.get_feature_set(args.feature_set or gdi.DEFAULT_FEATURE_SET)
    reference = gdi.load_gdi_reference(args.reference, feature_set)

    any_alert = False
    for session in args.sessions:
        report = session_report(session, reference, feature_set,
                                args.conversion, gdi)
        print(format_report(report))
        print()
        any_alert = any_alert or bool(alerts(report))
    return 2 if any_alert else 0


if __name__ == "__main__":
    raise SystemExit(main())
