"""Gait Deviation Index (GDI), parameterised by feature set.

Recovered from the pre-rewrite `Examples/gaitAnalysis-UCM.py` (commit 3a568fb),
repaired 2026-08-25, and parameterised 2026-08-27 (Phase 3.1 of
`docs/plans/2026-08-27-001-feat-rerun-visualizer-joint-reduction-plan.md`).

GDI (Schwartz & Rozumalski 2008) scores a subject's gait kinematics against a
normative control group: 100 means the control mean, and every 10 points below
that is one standard deviation away. The canonical form uses 9 kinematic
variables sampled at 51 points across the gait cycle, projected onto reference
eigenvectors, with the log Euclidean distance from the control mean converted
to a z-score.

    subject = matrix @ feature_vector
    diff    = subject - control_mean
    z       = (ln(||diff||) - ln_control_mean) / ln_control_sd
    GDI     = 100 - 10 * z

**Why this is parameterised.** The lab does not use one feature set, it uses
four, and the archived reference matrices in `control_kinematics/` prove it by
their row counts -- every matrix is `n_variables x 51` rows:

    459 rows = 9 vars   matrix_control.csv          the canonical set
    306 rows = 6 vars   matrix_ms_reduced_old.csv   canonical minus pelvis
    255 rows = 5 vars   matrix_ms_reduced.csv       the live MS path
    204 rows = 4 vars   matrix_sci_reduced.csv      the SCI path

The old module hardcoded 9 variables / 459 values while defaulting to a
255-row matrix, so `compute_gdi` raised a shape mismatch on **every** call:
GDI could not return a number at all. A feature set now carries its own
variables, its own reference filenames, and its own normative constants
together, because a wrong pairing of those three is exactly what produced that.

**Two provenance findings worth keeping.**

1. *The ninth variable is `fpa`, not `subtalar_angle`.* The original file
   contained both spellings in different commented blocks (`subtalar_angle_l`
   at its line 392, `fpa_l` at its line 1020) and the 2026-08-25 recovery
   picked the wrong one. The supervisor's current script uses `fpa`, and the
   to-do note is explicit ("last 2 are fpa values"). Every feature vector
   built before today was wrong in its last 51 values.

2. *The old normative constants came from a commented-out line.* The
   `4.443685139 / 0.223457646` pair carried by the previous version appears
   in the original only inside `# z_score = (ln_result - 4.443685139)/...`,
   and in no live code path anywhere. The constants the supervisor's script
   actually executes are cohort-specific and different. Unattributable
   constants are now `None` rather than silently applied -- see below.

**A feature set with no normative constants cannot score, by design.**
`ln_control_mean`/`ln_control_sd` are properties of one control group
projected through one matrix; they are not properties of GDI. Where they
could not be attributed to a feature set from the recovered code, they are
`None` and `compute_gdi` refuses rather than guessing. Regenerating them is
Phase 3.3, and doing so invalidates any previously reported score.

**The promoted constants belong to the regenerated references, not the
archived ones.** Every shipped set's constants were derived on 2026-08-27 from
the 166-cycle healthy-control cohort, and they are only valid against the
bases produced in the same run (written by `gdi_reference.py` to
`context/gdi_reference_2026-08-27/`). Pairing them with the *archived*
matrices of the same filename is the same class of error this module exists to
prevent, and it is not hypothetical: scoring the control cohort through the
archived bases with these constants gives 100.8 for gdi9 and 96.6 for
reduced4, but **118.0 for reduced5** -- controls reading as far better than
normal. That reduced5's archived basis is the one that misbehaves is
independent support for the msflag note below: a basis built from the MS
cohort projects control cycles differently. Point `reference_dir` at the
regenerated set, where all four score controls at exactly 100.0 +/- 10.0.

**This module cannot produce a score without reference data.** `matrix` and
`control_mean` come from a normative control dataset that is NOT in this
repository. That is a missing dataset, not a missing feature -- GDI is
*defined* relative to a control group.

Note on this project's IMU pipeline: no GDI feature is a translation or a
centre-of-mass term, so GDI is unaffected by the pinned-root limitation that
invalidates gait_speed/stride_length for IMU-derived trials.
"""
import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# GDI samples the gait cycle at 51 points: every other frame of the
# 101-point normalised cycle (the original's `if (num % 2 == 0)`). This is
# fixed across every feature set -- only the variable list varies.
GDI_CYCLE_POINTS = tuple(range(0, 101, 2))
GDI_N_POINTS = len(GDI_CYCLE_POINTS)  # 51

# The canonical nine, in reference-matrix order. Order matters: it must match
# the row order of the reference matrix, so do not sort or regroup. Every
# reduced set below is a contiguous tail of this list, which is not a
# coincidence -- the reductions were built as row slices of the 459-row
# vector (`indiv_data[153::]` and friends).
_CANONICAL_9 = (
    "pelvis_tilt",
    "pelvis_list",
    "pelvis_rotation",
    "hip_flexion_{side}",
    "hip_adduction_{side}",
    "hip_rotation_{side}",
    "knee_angle_{side}",
    "ankle_angle_{side}",
    "fpa_{side}",
)

# Per-variable corrections, applied when the variable is present and skipped
# when it is not. Keyed by template name so a reduced set that drops pelvis
# automatically drops the corrections with it -- the previous version applied
# them from an `if name ==` chain that would have gone looking for pelvis
# columns that a 6-variable set does not have.
_CURVE_ADJUSTMENTS = {
    "pelvis_tilt": lambda value: value + 20.0,
    "pelvis_rotation": lambda value: value - 180.0 if value > 180.0 else value,
}


@dataclass(frozen=True)
class GdiFeatureSet:
    """One feature set and the reference data it is defined against.

    The four fields after `features` travel together deliberately. A matrix
    built for 5 variables, a control mean of a different width, and normative
    constants from a third cohort will each produce a plausible number and a
    wrong one; keeping them in one object is what makes a mismatch a
    construction error rather than a silent result.
    """

    name: str
    features: tuple
    matrix_filename: str
    control_filename: str
    ln_control_mean: float = None
    ln_control_sd: float = None
    provenance: str = ""

    @property
    def n_features(self):
        return len(self.features)

    @property
    def vector_length(self):
        return self.n_features * GDI_N_POINTS

    @property
    def can_score(self):
        """False when the normative constants were never attributed. Such a
        set can still build vectors and project them; it just cannot convert
        a distance into a score."""
        return self.ln_control_mean is not None and self.ln_control_sd is not None

    def feature_names(self, side):
        if side not in ("r", "l"):
            raise ValueError(f"side must be 'r' or 'l', got {side!r}")
        return tuple(name.format(side=side) for name in self.features)


GDI9 = GdiFeatureSet(
    name="gdi9",
    features=_CANONICAL_9,
    matrix_filename="matrix_control.csv",
    control_filename="controlcalc_control.csv",
    ln_control_mean=4.716953,
    ln_control_sd=0.292494,
    provenance=(
        "Canonical Schwartz & Rozumalski set. Constants regenerated 2026-08-27 "
        "by gdi_reference.py from the 166-cycle pooled healthy-control cohort "
        "(control_kinematics.csv), 15 components, 98.67% of variance; held-out "
        "controls score 100.32 +/- 10.26. They corroborate the recovered "
        "fallback `(ln_result - 4.69)/0.30` to within 0.57%, which was a real "
        "calibration stranded in a branch referencing an undefined `ln_result`."
    ),
)

REDUCED6 = GdiFeatureSet(
    name="reduced6",
    features=_CANONICAL_9[3:],
    matrix_filename="matrix_ms_reduced_old.csv",
    control_filename="controlCalc_ms_reduced_old.csv",
    ln_control_mean=4.642758,
    ln_control_sd=0.300381,
    provenance=(
        "The canonical nine minus the three pelvis terms, recovered from the "
        "supervisor's `indiv_data[153::]` slice (rows 153-458 = 306 = 6 x 51). "
        "matrix_ms_reduced_old.csv is 306x27 and pairs with a 1x27 controlCalc; "
        "old2/old3 (306x31) and old4 (306x34) are the same variables with more "
        "components retained. Constants regenerated 2026-08-27 from the "
        "166-cycle healthy-control cohort, 15 components, 99.07% of variance; "
        "held-out controls score 100.18 +/- 10.31. No archived constant existed "
        "for this set to compare against."
    ),
)

REDUCED5 = GdiFeatureSet(
    name="reduced5",
    features=_CANONICAL_9[3:5] + _CANONICAL_9[6:],
    matrix_filename="matrix_ms_reduced.csv",
    control_filename="controlCalc_ms_reduced.csv",
    ln_control_mean=4.448830,
    ln_control_sd=0.281448,
    provenance=(
        "The live path in the supervisor's current script: "
        "`np.concatenate((indiv_data[153:255], indiv_data[306:459]))` = hip "
        "flexion/adduction plus knee, ankle and fpa (255 = 5 x 51). Constants "
        "regenerated 2026-08-27 from the 166-cycle healthy-control cohort, 15 "
        "components, 99.45% of variance; held-out controls score 100.03 +/- "
        "10.27. They corroborate the commented-out 4.443685139 to within 0.12% "
        "-- that value was a correct reduced5 calibration which the 2026-08-25 "
        "recovery mis-attached to a 9-variable feature list. "
        "SUPERSEDED: the script's live `msflag` constants (3.64317 / 0.54211) "
        "are 22% from the control-derived mean with nearly double the SD, while "
        "every other archived constant matches its regeneration within 0.6%. "
        "That gap is consistent with msmean/mssd having been computed from the "
        "MS cohort rather than from controls, which would make scores under "
        "them deviation relative to MS rather than GDI. Unconfirmed -- the "
        "derivation is not in any recovered source."
    ),
)

REDUCED4 = GdiFeatureSet(
    name="reduced4",
    features=_CANONICAL_9[3:5] + _CANONICAL_9[6:8],
    matrix_filename="matrix_sci_reduced.csv",
    control_filename="controlcalc_sci_reduced.csv",
    ln_control_mean=4.264782,
    ln_control_sd=0.316835,
    provenance=(
        "The SCI path: `indiv_data[153:255]` + `[306:408]`, dropping fpa as "
        "well as pelvis (204 = 4 x 51). Constants are the script's literal "
        "regenerated 2026-08-27 from the 166-cycle healthy-control cohort, 15 "
        "components, 99.71% of variance; held-out controls score 100.01 +/- "
        "10.12. The archived `sciflag` pair (4.518094 / 0.415455) is 5.9% away "
        "and is superseded; if it was derived from the SCI cohort it carries "
        "the same concern recorded on reduced5. Note matrix.csv has the same "
        "shape (204x14) and appears to be a copy of matrix_sci_reduced.csv "
        "under the generic name."
    ),
)

FEATURE_SETS = {fs.name: fs for fs in (GDI9, REDUCED6, REDUCED5, REDUCED4)}

# reduced6 is the project default as of 2026-08-28, by explicit decision: the
# supervisor's 2026-08-27 note asks for "6 joints instead of 26 joints", and
# the six recovered here are the canonical nine minus pelvis.
#
# GDI9 remains the standards-canonical set and is still shipped; it is simply
# not what this project scores against. Two practical consequences of the
# choice, both in its favour: reduced6 drops the pelvis terms, so neither the
# `pelvis_tilt` +20 offset nor the `pelvis_rotation` wrap can misalign a
# subject vector against the reference, and its 15 components capture 99.07%
# of control variance against 98.67% for the nine.
#
# Scores are NOT comparable across feature sets. Changing this constant
# changes every number the project reports.
DEFAULT_FEATURE_SET = REDUCED6


def get_feature_set(name):
    """Look a feature set up by name, listing the alternatives on a miss."""
    # Duck-typed, not isinstance: this repo loads modules by path (see
    # module_loading.py), so the same gdi.py can be live under two different
    # module objects at once and an isinstance check would reject a perfectly
    # good feature set built from the other one.
    if hasattr(name, "features") and hasattr(name, "vector_length"):
        return name
    try:
        return FEATURE_SETS[name]
    except KeyError:
        raise KeyError(
            f"unknown GDI feature set {name!r}; available: "
            f"{sorted(FEATURE_SETS)}"
        ) from None


def canonical_row_indices(feature_set=DEFAULT_FEATURE_SET):
    """Row indices of this feature set inside the canonical 459-row vector.

    The pooled cohort matrices on disk are stored in canonical 9-variable
    order (`control_kinematics.csv` is 459 x n_cycles), and every reduced set
    is a subset of those variables. Building a reduced reference therefore
    means selecting rows, which is exactly what the supervisor's
    `indiv_data[153::]` slices did -- generalised here so a non-contiguous
    set (reduced5 drops hip_rotation from the middle) works too.
    """
    feature_set = get_feature_set(feature_set)
    canonical = list(_CANONICAL_9)
    indices = []
    for template in feature_set.features:
        try:
            position = canonical.index(template)
        except ValueError:
            raise ValueError(
                f"feature {template!r} is not one of the canonical nine, so its "
                "rows cannot be located in a pooled cohort matrix."
            ) from None
        start = position * GDI_N_POINTS
        indices.extend(range(start, start + GDI_N_POINTS))
    return np.array(indices, dtype=int)


class GdiReferenceMissingError(FileNotFoundError):
    """The normative reference data GDI is defined against is not available.
    Distinct from a generic FileNotFoundError so callers can tell "you have
    not supplied the control dataset" apart from "a path is wrong"."""


class GdiConstantsMissingError(ValueError):
    """The feature set has no attributed normative constants, so a distance
    cannot be converted into a score. Distinct from a shape error: the
    projection is fine, the calibration is absent."""


def gdi_features(side, feature_set=DEFAULT_FEATURE_SET):
    """The variable names for 'r' or 'l', in reference-matrix order."""
    return get_feature_set(feature_set).feature_names(side)


def load_gdi_reference(directory, feature_set=DEFAULT_FEATURE_SET):
    """Load the normative reference data for one feature set.

    Validates two things the previous version did not check together: that the
    matrix and the control mean project into the same number of dimensions,
    and that the matrix expects vectors of exactly this feature set's length.
    The second is what turns the old silent 459-vs-255 mismatch into a load
    error naming both numbers, at the point where the wrong file was chosen.
    """
    feature_set = get_feature_set(feature_set)
    directory = Path(directory)
    matrix_path = directory / feature_set.matrix_filename
    control_path = directory / feature_set.control_filename

    missing = [p.name for p in (matrix_path, control_path) if not p.is_file()]
    if missing:
        raise GdiReferenceMissingError(
            f"GDI reference data for feature set {feature_set.name!r} not found in "
            f"{directory}: missing {missing}. GDI is defined relative to a "
            "normative control group, so it cannot be computed without this "
            f"dataset -- it is not derivable from subject data. Both "
            f"{feature_set.matrix_filename} and {feature_set.control_filename} "
            "are required."
        )

    with open(matrix_path, "r", newline="") as handle:
        matrix = np.array(list(csv.reader(handle)), dtype=float)
    # Transposed on load, preserving the original's `np.transpose(matrix)`:
    # the file is stored (vector_length x n_components), and the projection
    # wants (n_components x vector_length).
    matrix = matrix.T

    with open(control_path, "r", newline="") as handle:
        control_mean = np.array(
            [float(value) for row in csv.reader(handle) for value in row], dtype=float
        )

    if matrix.shape[0] != control_mean.shape[0]:
        raise ValueError(
            f"{feature_set.matrix_filename} projects into {matrix.shape[0]} "
            f"dimensions but {feature_set.control_filename} has "
            f"{control_mean.shape[0]} values. These come from the same control "
            "dataset and must agree."
        )

    if matrix.shape[1] != feature_set.vector_length:
        raise ValueError(
            f"{feature_set.matrix_filename} expects a {matrix.shape[1]}-value "
            f"feature vector, but feature set {feature_set.name!r} builds "
            f"{feature_set.vector_length} ({feature_set.n_features} variables x "
            f"{GDI_N_POINTS} points). The matrix was built for a different "
            f"feature set -- {matrix.shape[1] / GDI_N_POINTS:g} variables, if it "
            "uses the same 51-point sampling."
        )

    return {
        "matrix": matrix,
        "control_mean": control_mean,
        "feature_set": feature_set,
    }


def build_gdi_feature_vector(mean_curves, side, feature_set=DEFAULT_FEATURE_SET):
    """Flatten one side's mean gait-cycle curves into this set's feature vector.

    `mean_curves` maps coordinate name -> a 101-point normalised cycle, i.e.
    gait_analysis results' `curves_<side>['mean']`.
    """
    feature_set = get_feature_set(feature_set)
    features = feature_set.feature_names(side)
    missing = [name for name in features if name not in mean_curves]
    if missing:
        raise KeyError(
            f"mean curves are missing GDI coordinate(s) {missing}. Feature set "
            f"{feature_set.name!r} needs all {feature_set.n_features}: "
            f"{list(features)}."
        )

    values = []
    for template, name in zip(feature_set.features, features):
        curve = mean_curves[name]
        if len(curve) < 101:
            raise ValueError(
                f"coordinate {name!r} has {len(curve)} points; GDI needs a "
                f"101-point normalised gait cycle to sample {GDI_N_POINTS} from."
            )
        adjust = _CURVE_ADJUSTMENTS.get(template)
        for point in GDI_CYCLE_POINTS:
            value = float(curve[point])
            values.append(adjust(value) if adjust else value)

    vector = np.array(values, dtype=float)
    assert vector.shape == (feature_set.vector_length,), vector.shape
    return vector


def compute_gdi(feature_vector, reference, feature_set=None):
    """GDI score for one side. 100 = control mean; each 10 points below is
    one SD from it.

    `feature_set` defaults to whichever set the reference was loaded for, so
    the constants and the matrix cannot drift apart at the call site.
    """
    if feature_set is None:
        feature_set = reference.get("feature_set", DEFAULT_FEATURE_SET)
    feature_set = get_feature_set(feature_set)

    if not feature_set.can_score:
        raise GdiConstantsMissingError(
            f"feature set {feature_set.name!r} has no attributed normative "
            "constants (ln_control_mean / ln_control_sd), so a distance cannot "
            "be converted into a score. These are properties of one control "
            "group projected through one matrix, not of GDI, and guessing them "
            "would produce a plausible wrong number. Regenerate them from the "
            f"control cohort. Provenance: {feature_set.provenance}"
        )

    feature_vector = np.asarray(feature_vector, dtype=float)
    matrix = reference["matrix"]

    if matrix.shape[1] != feature_vector.shape[0]:
        raise ValueError(
            f"GDI reference matrix expects a {matrix.shape[1]}-value feature "
            f"vector but got {feature_vector.shape[0]}. Feature set "
            f"{feature_set.name!r} is defined on {feature_set.n_features} "
            f"variables x {GDI_N_POINTS} points = {feature_set.vector_length}; "
            "if the reference matrix disagrees, it was built for a different "
            "feature set."
        )

    subject = matrix @ feature_vector
    diff = subject - reference["control_mean"]
    distance = math.sqrt(float(np.sum(np.square(diff))))
    if distance <= 0.0:
        # A subject identical to the control mean; log(0) is undefined and the
        # score is 100 by definition rather than by computation.
        return 100.0
    z_score = (math.log(distance) - feature_set.ln_control_mean) / feature_set.ln_control_sd
    return 100.0 - 10.0 * z_score


def gdi_for_trial(results, reference, feature_set=None):
    """GDI for both sides of one trial, plus their average.

    `results` carries `curves_r` and `curves_l`, as returned by the gait
    analysis run.
    """
    if feature_set is None:
        feature_set = reference.get("feature_set", DEFAULT_FEATURE_SET)
    feature_set = get_feature_set(feature_set)

    scores = {}
    for side, key in (("r", "curves_r"), ("l", "curves_l")):
        if key not in results:
            raise KeyError(f"results has no {key!r}; cannot score the {side} side.")
        vector = build_gdi_feature_vector(results[key]["mean"], side, feature_set)
        scores[side] = compute_gdi(vector, reference, feature_set)
    scores["average"] = (scores["r"] + scores["l"]) / 2.0
    return scores
