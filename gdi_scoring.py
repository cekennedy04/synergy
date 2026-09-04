"""Pooled GDI for one session, without dragging matplotlib in behind it.

Split out of `session_report.py` on 2026-09-04 so the clinician GUI can score
a session it has just processed. The GUI could not call `session_report`
directly, and the reason is worth stating because it is not obvious and it is
silent:

    `session_report.py` calls `matplotlib.use("Agg")` at import, correctly --
    it is a batch report generator with no display. But `matplotlib.use` is
    process-wide. Importing it from inside the running GUI would switch that
    process to a backend that renders to a file and never opens a window,
    which would disable the gait-event picker: `plt.show()` returns instantly
    under Agg, `segment_walking` reads the resulting empty picker as the
    operator declining, and every unsegmentable trial would quietly fall back
    to auto-trim with nobody told. `gait_event_picker_ui` documents that trap
    and raises on it; this module is how the GUI avoids setting it off.

Everything here is numpy and csv. No matplotlib, no tkinter, no OpenSim.

**Why the synergy index is not in this module.** It is not an oversight and
it is not symmetry: the synergy index needs `task_functions.OpenSimModel`,
and more importantly it is not defensible at the level a GUI has. UCM
decomposes variance *across strides*; a single trial carries four to six,
which is a very thin basis for splitting a 15-dimensional nullspace from its
3-dimensional complement. `session_report`'s own docstring makes this
argument and concludes that the session figure is the one to quote. GDI is
different and both levels are meaningful -- it scores a mean curve against a
normative reference, so it is well defined for as little as one stride.

So this module scores GDI for anyone who has a pooled matrix, and the synergy
index stays where the strides to estimate it are.
"""
import csv
import importlib.util
import re
from collections import OrderedDict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent


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


def score_pooled_gdi(session_dir, reference_dir, conversion="ik",
                     feature_set=None, gdi=None, curves=None):
    """GDI over every pooled stride in the session, per side.

    Returns ``{"gdi": {...}, "by_trial": {...}}`` in the shape
    `trial_scores.summary_for_report` and `report_export._build_gdi_figure`
    already expect, so neither has to learn a second one.

    A side with no pooled matrix is absent from the result rather than
    present with a placeholder: the report prints what is missing, and a NaN
    in a results table is indistinguishable from a measurement.
    """
    gdi = gdi or _load("_gdi_for_scoring", "gdi.py")
    curves = curves or _load("_curves_for_scoring", "curve_features.py")

    feature_set = gdi.get_feature_set(feature_set or gdi.DEFAULT_FEATURE_SET)
    reference = gdi.load_gdi_reference(reference_dir, feature_set)
    row_order = curves.exported_row_order()
    paths = pooled_paths(session_dir, conversion)

    scores = {}
    by_trial = {}
    for side, entry in paths.items():
        matrix = curves.load_curve_matrix(entry["matrix"], row_order)
        per_stride = curves.score_curves(matrix, side, reference, feature_set,
                                         gdi, row_order)
        scores[side] = {
            "mean": float(np.mean(per_stride)),
            "sd": float(np.std(per_stride)) if per_stride.size > 1 else None,
            "n_strides": int(per_stride.size),
            "per_stride": [float(v) for v in per_stride],
        }
        trials = stride_trials(entry["index"])
        # Only when the sidecar accounts for every column. A partial mapping
        # would silently attribute strides to the wrong trials, which is the
        # exact shape of a drift finding that is not real.
        if len(trials) == per_stride.size:
            by_trial[side] = gdi_by_trial(per_stride, trials)
    scores["feature_set"] = feature_set.name
    return {"gdi": scores, "by_trial": by_trial}
