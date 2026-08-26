"""Gait Deviation Index (GDI), recovered and repaired from the pre-rewrite
Examples/gaitAnalysis-UCM.py (commit 3a568fb).

The original was ~810 lines of 100% commented-out code removed on 2026-08-17
as dead weight (see VENDORING.md). This module restores the calculation as
live, testable code with the bugs fixed. It is a NEW file, not an edit of a
coworker-supplied one -- the same pattern as gait_analysis_UCM_fixed.py.

GDI (Schwartz & Rozumalski 2008) scores a subject's gait kinematics against a
normative control group: 100 means the control mean, and every 10 points below
that is one standard deviation away. The score is computed from 9 kinematic
variables sampled at 51 points across the gait cycle, projected onto a set of
reference eigenvectors, with the log Euclidean distance from the control mean
converted to a z-score.

    subject = matrix @ feature_vector
    diff    = subject - control_mean
    z       = (ln(||diff||) - LN_CONTROL_MEAN) / LN_CONTROL_SD
    GDI     = 100 - 10 * z

**This module cannot produce a score without reference data.** `matrix` and
`control_mean` come from a normative control dataset that is NOT in this
repository (see `load_gdi_reference`). That is a missing dataset, not a
missing feature -- GDI is *defined* relative to a control group.

Note on this project's IMU pipeline: the 9 GDI features are joint angles plus
pelvis ORIENTATION (tilt/list/rotation). None of them is a translation or a
centre-of-mass term, so GDI is unaffected by the pinned-root limitation that
invalidates gait_speed/stride_length for IMU-derived trials. All 9 are present
in the IMU .mot output (verified 2026-08-25).

Bugs fixed relative to the recovered original, each of which would have
produced a wrong answer or a crash rather than an obvious failure:

 1. It checked for `matrix.csv` but opened `matrix_ms_reduced.csv`, and
    checked for `controlCalc.csv` but opened `controlCalc_ms_reduced.csv`.
    Whichever way the directory was populated, one of those two paths was
    wrong: a missing `_ms_reduced` file raised FileNotFoundError, and a
    missing plain-named file skipped the block silently, leaving `matrix`
    undefined until a NameError much later.
 2. It searched with `os.walk` from `dirname(dirname(dirname(__file__)))` --
    three levels above the repo -- and did not `break` on a match, so the
    LAST copy found anywhere in that tree silently won. Reference data is now
    an explicit directory argument.
 3. The right-leg feature vector was built from all 36 coordinates at 101
    points (3636 values) with the `num % 2 == 0` downsampling commented out,
    while the left-leg version used the correct 9-variable `joint_names2` list
    at 51 points. GDI is defined on 9 x 51; the right-leg vector was neither
    the right features nor the right sampling.
 4. The reference load ran at module import time, walking the filesystem as a
    side effect of importing the module.
 5. Nothing validated that the feature vector length matched the reference
    matrix, so a shape mismatch surfaced as an opaque numpy dot-product error.
"""
import csv
import math
from pathlib import Path

import numpy as np

# The 9 kinematic variables GDI is defined on, per side. Preserved from the
# original's `joint_names2` (which listed the left side); the right-side names
# mirror it. Order matters -- it must match the column order of the reference
# matrix, so do not sort or regroup these.
_GDI_FEATURES_TEMPLATE = (
    "pelvis_tilt",
    "pelvis_list",
    "pelvis_rotation",
    "hip_flexion_{side}",
    "hip_adduction_{side}",
    "hip_rotation_{side}",
    "knee_angle_{side}",
    "ankle_angle_{side}",
    "subtalar_angle_{side}",
)

# GDI samples the gait cycle at 51 points: every other frame of the
# 101-point normalised cycle (the original's `if (num % 2 == 0)`).
GDI_CYCLE_POINTS = tuple(range(0, 101, 2))
GDI_N_POINTS = len(GDI_CYCLE_POINTS)  # 51
GDI_N_FEATURES = len(_GDI_FEATURES_TEMPLATE)  # 9
GDI_VECTOR_LENGTH = GDI_N_FEATURES * GDI_N_POINTS  # 459

# Normative constants: the mean and SD of the natural log of the Euclidean
# distance between subjects and controls, across the reference control group.
# Carried over verbatim from the original -- they belong to the same control
# dataset as matrix/controlCalc and must be replaced together if that dataset
# is ever swapped.
LN_CONTROL_MEAN = 4.443685139
LN_CONTROL_SD = 0.223457646

MATRIX_FILENAME = "matrix_ms_reduced.csv"
CONTROL_FILENAME = "controlCalc_ms_reduced.csv"


class GdiReferenceMissingError(FileNotFoundError):
    """Raised when the normative reference data GDI is defined against is not
    available. Distinct from a generic FileNotFoundError so callers can tell
    "you have not supplied the control dataset" apart from "a path is wrong".
    """


def gdi_features(side):
    """The 9 GDI variable names for 'r' or 'l', in reference-matrix order."""
    if side not in ("r", "l"):
        raise ValueError(f"side must be 'r' or 'l', got {side!r}")
    return tuple(name.format(side=side) for name in _GDI_FEATURES_TEMPLATE)


def load_gdi_reference(directory):
    """Load the normative reference data from an explicit directory.

    Expects `matrix_ms_reduced.csv` (the eigenvector matrix) and
    `controlCalc_ms_reduced.csv` (the control-group mean in that projected
    space). Raises GdiReferenceMissingError naming exactly what is absent,
    rather than the original's silent skip followed by a later NameError.
    """
    directory = Path(directory)
    matrix_path = directory / MATRIX_FILENAME
    control_path = directory / CONTROL_FILENAME

    missing = [p.name for p in (matrix_path, control_path) if not p.is_file()]
    if missing:
        raise GdiReferenceMissingError(
            f"GDI reference data not found in {directory}: missing {missing}. "
            "GDI is defined relative to a normative control group, so it "
            "cannot be computed without this dataset -- it is not derivable "
            f"from subject data. Both {MATRIX_FILENAME} and "
            f"{CONTROL_FILENAME} are required."
        )

    with open(matrix_path, "r", newline="") as handle:
        matrix = np.array(list(csv.reader(handle)), dtype=float)
    # Transposed on load, preserving the original's `np.transpose(matrix)`.
    matrix = matrix.T

    with open(control_path, "r", newline="") as handle:
        control_mean = np.array(
            [float(value) for row in csv.reader(handle) for value in row], dtype=float
        )

    if matrix.shape[0] != control_mean.shape[0]:
        raise ValueError(
            f"{MATRIX_FILENAME} projects into {matrix.shape[0]} dimensions but "
            f"{CONTROL_FILENAME} has {control_mean.shape[0]} values. These come "
            "from the same control dataset and must agree."
        )
    return {"matrix": matrix, "control_mean": control_mean}


def build_gdi_feature_vector(mean_curves, side):
    """Flatten one side's mean gait-cycle curves into GDI's 459-value vector.

    `mean_curves` maps coordinate name -> a 101-point normalised cycle, i.e.
    gait_analysis results' `curves_<side>['mean']`.

    Reproduces the original's two per-coordinate adjustments exactly:
    pelvis_tilt is offset by +20 degrees, and pelvis_rotation is wrapped by
    subtracting 180 when it exceeds 180.
    """
    features = gdi_features(side)
    missing = [name for name in features if name not in mean_curves]
    if missing:
        raise KeyError(
            f"mean curves are missing GDI coordinate(s) {missing}. GDI needs all "
            f"{GDI_N_FEATURES}: {list(features)}."
        )

    values = []
    for name in features:
        curve = mean_curves[name]
        if len(curve) < 101:
            raise ValueError(
                f"coordinate {name!r} has {len(curve)} points; GDI needs a "
                "101-point normalised gait cycle to sample 51 from."
            )
        for point in GDI_CYCLE_POINTS:
            value = float(curve[point])
            if name == "pelvis_tilt":
                value += 20.0
            elif name == "pelvis_rotation" and value > 180.0:
                value -= 180.0
            values.append(value)

    vector = np.array(values, dtype=float)
    assert vector.shape == (GDI_VECTOR_LENGTH,), vector.shape
    return vector


def compute_gdi(feature_vector, reference):
    """GDI score for one side. 100 = control mean; each 10 points below is
    one SD from it."""
    feature_vector = np.asarray(feature_vector, dtype=float)
    matrix = reference["matrix"]

    # Checked explicitly: a mismatch here would otherwise surface as an opaque
    # numpy dot-product error with no indication of which side was wrong.
    if matrix.shape[1] != feature_vector.shape[0]:
        raise ValueError(
            f"GDI reference matrix expects a {matrix.shape[1]}-value feature "
            f"vector but got {feature_vector.shape[0]}. GDI is defined on "
            f"{GDI_N_FEATURES} variables x {GDI_N_POINTS} points = "
            f"{GDI_VECTOR_LENGTH}; if the reference matrix disagrees, it was "
            "built for a different feature set."
        )

    subject = matrix @ feature_vector
    diff = subject - reference["control_mean"]
    distance = math.sqrt(float(np.sum(np.square(diff))))
    if distance <= 0.0:
        # A subject identical to the control mean; log(0) is undefined and the
        # score is 100 by definition rather than by computation.
        return 100.0
    z_score = (math.log(distance) - LN_CONTROL_MEAN) / LN_CONTROL_SD
    return 100.0 - 10.0 * z_score


def gdi_for_trial(results, reference):
    """GDI for both sides of one trial, plus their average.

    `results` is the dict returned by Examples/gaitAnalysis-UCM.py's
    run_gait_analysis (it carries `curves_r` and `curves_l`).
    """
    scores = {}
    for side, key in (("r", "curves_r"), ("l", "curves_l")):
        if key not in results:
            raise KeyError(f"results has no {key!r}; cannot score the {side} side.")
        vector = build_gdi_feature_vector(results[key]["mean"], side)
        scores[side] = compute_gdi(vector, reference)
    scores["average"] = (scores["r"] + scores["l"]) / 2.0
    return scores
