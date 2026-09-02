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
the 166-cycle healthy-control cohort at 15 components, and are only valid
against the bases produced in the same run (written by `gdi_reference.py`).
Scoring the control cohort through the *archived* matrices with them gives
100.8 (gdi9), 96.6 (reduced4), 97.6 (reduced6) and 118.0 (reduced5).

The reason is column scaling, not provenance. Two of the archived matrices are
not orthonormal bases at all: `matrix_ms_reduced.csv` and
`matrix_ms_reduced_old.csv` have column norms from 0.03 to 1.0 and MtM
departing from the identity by ~1.0, so projections onto most of their columns
are shrunk 5-30x and distances collapse. Taking a purely *control*-derived
basis and rescaling its columns to the archived norms overshoots the observed
118, so the effect needs no other explanation.

An earlier version of this comment inferred from reduced5's 118 that its basis
was MS-derived. That inference does not hold: reduced6's matrix is equally
non-orthonormal and scores an unremarkable 97.6, and controls projected
through the archived reduced5 basis have an empirical ln-distance of 3.94 --
nearer the archived msflag 3.64317 than the control-derived 4.44883, which
points the opposite way. The open question is narrower: which basis and
component count msmean/mssd were derived through. Do not repeat the stronger
claim.

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

# How far a reference matrix may depart from orthonormality before it is
# refused. Generous: a genuine SVD basis lands at ~1e-6, the loosest
# legitimate archived one at ~1e-3, and the two rescaled files at ~1.0.
ORTHONORMALITY_TOLERANCE = 1e-2

# What one score is computed from. This is a property of the *calibration*,
# not a stylistic choice: `ln_control_mean`/`ln_control_sd` are the mean and SD
# of the control cohort's log distances, and the cohort's columns are
# individual gait cycles. A subject's mean curve is a different kind of object
# -- averaging strides removes stride-to-stride noise, so a mean curve sits
# closer to the control mean than any of the cycles it was built from, and
# scoring it against a per-cycle norm reads high. Measured high on every leg
# tested here; not proved to be high universally, since the constants are
# moments of the *log* distances and no general ordering follows from
# convexity alone.
#
# Measured on the 90 exported trial-legs in `context/gait_curves/`: the mean
# curve scores +0.53 above the mean of the per-stride scores on average, +3.30
# at worst, and the gap tracks within-trial stride variability (r = 0.62)
# rather than stride count (r = -0.16). It grows as a subject approaches
# normal, because a subject far from the control mean is dominated by
# systematic deviation that averaging cannot remove -- so the bias is worst
# exactly where discrimination matters most.
#
# See docs/2026-08-31-gdi-vs-ucm-audit.md section 3.
SCORING_UNIT_CYCLE = "cycle"
SCORING_UNIT_MEAN_CURVE = "mean_curve"
SCORING_UNITS = (SCORING_UNIT_CYCLE, SCORING_UNIT_MEAN_CURVE)

# The canonical nine, in reference-matrix order. Order matters: it must match
# the row order of the reference matrix, so do not sort or regroup. Every
# reduced set below is a subset of it, built as row slices of the 459-row
# vector (`indiv_data[153::]` and friends). reduced6 is a contiguous tail;
# reduced5 and reduced4 are NOT -- they drop hip_rotation from the middle.
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
#
# The `+20` on pelvis_tilt was REMOVED 2026-09-02. It was a legacy correction
# for an input pipeline whose raw tilt sat near 0 to -8 degrees, and it is not
# one for this pipeline: our raw exports mean 21.23 degrees (n=3 subjects, 90
# trial-legs), so +20 took them to 41.23. Published norms put healthy anterior
# pelvic tilt near 12 +/- 4 (Schwartz 2008, Davis 1991) and the control cohort
# this project scores against stores 11.99, so 41 is not a convention -- it is
# non-physiological, and wrong regardless of which frame turns out to be
# authoritative. Removing it needed no answer to that question; what replaces
# it does.
#
# Do NOT replace it with a fitted offset. Aligning our subjects' mean tilt to
# the cohort's (a -9.24 shift) was considered and rejected: it is estimated
# from three subjects of unverified health status, its between-subject spread
# (6.5 degrees) is 70% of the offset itself, and mean-matching a *subject*
# group onto a *control* reference removes precisely the between-group
# difference GDI exists to measure. See section 12 of
# docs/2026-08-31-gdi-vs-ucm-audit.md for the measurements.
#
# The remaining `pelvis_rotation` wrap is a range fix, not a frame correction:
# it maps a value reported near +360 back into +/-180. It stands on its own.
_CURVE_ADJUSTMENTS = {
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
    # The unit the constants above were calibrated on. Every shipped set is
    # `cycle`: the 166 columns of the pooled control cohort are gait cycles,
    # and both constants are moments of the per-cycle log distances.
    scoring_unit: str = SCORING_UNIT_CYCLE
    # sha256 of the exact (matrix, control_mean) pair these constants were
    # derived from -- see `reference_digest()`. Shape and orthonormality checks
    # cannot tell two well-formed bases apart, so they cannot catch a matrix
    # from a *different cohort* being paired with these constants. That
    # pairing produces a plausible wrong number: the archived gdi9 basis with
    # the regenerated constants scores healthy controls at 100.8, and the
    # archived reduced4 basis at 96.6 -- both close enough to normal to pass
    # unnoticed, and both wrong. `None` disables the check.
    reference_digest: str = None
    # Set to a sentence explaining why, when a set is known to produce wrong
    # numbers and must not be scored with. `get_feature_set` and `compute_gdi`
    # both refuse it. This is deliberately NOT waivable: unlike
    # `check_digest=False`, which lets an expert reproduce a historic result
    # from a reference that is merely unattributed, a disabled set is one whose
    # output is known to be wrong in a known direction, and there is no honest
    # reason to want that number.
    disabled_reason: str = None

    @property
    def n_features(self):
        return len(self.features)

    @property
    def is_disabled(self):
        return self.disabled_reason is not None

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
    reference_digest="ee05c4a85881b8a1079d001e5b1ef87f1d7ad17afe3734db5211fcfb5741d587",
    disabled_reason=(
        "this pipeline's joint-angle frame does not match the control cohort "
        "the references are calibrated on, and gdi9's three pelvis terms are "
        "among the worst-affected. Measured against the cohort, our exports "
        "differ by +9.24 deg on pelvis_tilt and +2.36 on pelvis_rotation. "
        "The mismatch is NOT confined to pelvis -- hip_flexion is off by "
        "-13.47 deg and fpa by +10.90 -- so reduced6 is not a fix for it, "
        "only a smaller exposure to it (6 variables' worth of offset rather "
        "than 9). gdi9 is disabled rather than reduced6 because gdi9 adds the "
        "pelvis terms on top without any offsetting benefit, and because the "
        "project's reported numbers all come through reduced6. Disabled until "
        "the frame question is resolved -- see section 12 of "
        "docs/2026-08-31-gdi-vs-ucm-audit.md. Note that this is a "
        "comparability problem, not a trimming one: auto-trimming recovers "
        "clean gait cycles, it does not recalibrate a coordinate frame."
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
        "166-cycle healthy-control cohort, 15 components, 99.07% of variance. "
        "No archived constant existed "
        "for this set to compare against."
    ),
    reference_digest="4e3072c8db729fb818381ca16d71a32664189622c05e29d3dc1acac9c7036f88",
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
        "components, 99.45% of variance. They corroborate the commented-out 4.443685139 to within 0.12% "
        "-- that value was a correct reduced5 calibration which the 2026-08-25 "
        "recovery mis-attached to a 9-variable feature list. "
        "The live `msflag` constants (3.64317 / 0.54211) are 18% below this and "
        "are superseded as a CONTROL reference, since GDI is defined against a "
        "non-disabled group. Nothing here establishes which cohort they came "
        "from: the archived matrix_ms_reduced.csv is not orthonormal, which "
        "accounts for the anomalies once attributed to cohort provenance."
    ),
    reference_digest="e5876a2dda9a3625a96a8601ebb1546cc2dd2cfdfc43bd43453c6e491731c87f",
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
        "components, 99.71% of variance. The archived `sciflag` pair (4.518094 / 0.415455) is 5.9% away "
        "and is superseded; if it was derived from the SCI cohort it carries "
        "the same concern recorded on reduced5. Note matrix.csv has the same "
        "shape (204x14) and appears to be a copy of matrix_sci_reduced.csv "
        "under the generic name."
    ),
    reference_digest="e4e5dde54df94f43772f064bf2442ba688cf4978b97b1b74a68385ad82fab1ef",
)

FEATURE_SETS = {fs.name: fs for fs in (GDI9, REDUCED6, REDUCED5, REDUCED4)}

# Every constant above was derived treating each of control_kinematics.csv's
# 166 columns as one independent observation. Settled 2026-09-01: that is
# correct -- a column is one stride, which is the unit GDI is defined on
# (Herrera-Valenzuela et al. 2022, "each column vector is a stride"; control
# groups counted in strides in every published derivation). The cohort does
# carry an 83-pair structure, so its effective size for a confidence interval
# is nearer 83 than 166, but the unit is right and the constants stand. An
# earlier proposal to rebuild them at 83 units is withdrawn -- see the ANSWERED
# comment in gdi_reference.build_reference for the full evidence.

# reduced6 is the project default as of 2026-08-28, by explicit decision: the
# supervisor's 2026-08-27 note asks for "6 joints instead of 26 joints", and
# the six recovered here are the canonical nine minus pelvis.
#
# GDI9 remains the standards-canonical set and its definition is kept here --
# the recovered feature order, the regenerated constants and the digest are all
# still needed to read the audit and to rebuild it once the pelvis convention
# is settled. It is DISABLED for scoring, not deleted. What was a preference
# for reduced6 is now also the only working option: reduced6 drops the pelvis
# terms, so neither the `pelvis_tilt` +20 offset nor the `pelvis_rotation` wrap
# can misalign a subject vector against the reference, and its 15 components
# capture 99.07% of control variance against 98.67% for the nine.
#
# Scores are NOT comparable across feature sets. Changing this constant
# changes every number the project reports.
DEFAULT_FEATURE_SET = REDUCED6


def get_feature_set(name):
    """Look a feature set up by name, listing the alternatives on a miss.

    Refuses a disabled set. This is the CLI's path -- `--feature-set gdi9`
    resolves here -- so it is where a request for a known-wrong set has to
    stop. Passing the feature-set *object* bypasses this by design (see the
    duck-typing note below); `compute_gdi` catches that path instead, so no
    route reaches a score.
    """
    # Duck-typed, not isinstance: this repo loads modules by path (see
    # module_loading.py), so the same gdi.py can be live under two different
    # module objects at once and an isinstance check would reject a perfectly
    # good feature set built from the other one.
    if hasattr(name, "features") and hasattr(name, "vector_length"):
        return name
    try:
        feature_set = FEATURE_SETS[name]
    except KeyError:
        raise KeyError(
            f"unknown GDI feature set {name!r}; available: "
            f"{sorted(FEATURE_SETS)}"
        ) from None
    if feature_set.is_disabled:
        raise GdiFeatureSetDisabledError(
            f"GDI feature set {feature_set.name!r} is disabled and cannot be "
            f"used. {feature_set.disabled_reason}"
        )
    return feature_set


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


def reference_digest(matrix, control_mean):
    """Fingerprint of one (matrix, control_mean) pair.

    Taken over the parsed float64 values rather than the file bytes, so it is
    insensitive to line endings, trailing newlines and CSV float formatting --
    all of which differ between the MATLAB that wrote the archived files and
    the `csv` module that writes the regenerated ones, while the numbers are
    the same. Little-endian is pinned so the digest is portable.
    """
    import hashlib

    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(matrix, dtype="<f8").tobytes())
    digest.update(np.ascontiguousarray(control_mean, dtype="<f8").tobytes())
    return digest.hexdigest()


class GdiReferenceMissingError(FileNotFoundError):
    """The normative reference data GDI is defined against is not available.
    Distinct from a generic FileNotFoundError so callers can tell "you have
    not supplied the control dataset" apart from "a path is wrong"."""


class GdiConstantsMissingError(ValueError):
    """The feature set has no attributed normative constants, so a distance
    cannot be converted into a score. Distinct from a shape error: the
    projection is fine, the calibration is absent."""


class GdiFeatureSetDisabledError(RuntimeError):
    """The feature set is known to produce wrong scores and has been taken out
    of service. Distinct from GdiConstantsMissingError, which means "we cannot
    compute a number": here we can, and the number would be wrong in a known
    direction. A RuntimeError rather than a ValueError because nothing about
    the caller's arguments is malformed -- the pipeline is not in a state where
    this set can be honestly scored."""


def gdi_features(side, feature_set=DEFAULT_FEATURE_SET):
    """The variable names for 'r' or 'l', in reference-matrix order."""
    return get_feature_set(feature_set).feature_names(side)


class GdiReferenceMismatchError(ValueError):
    """The reference on disk is not the one this feature set's normative
    constants were calibrated against. Distinct from a shape or orthonormality
    error: the matrix is a perfectly good basis, it just belongs to a different
    cohort or a different component count, and pairing it with these constants
    silently shifts every score."""


def load_gdi_reference(directory, feature_set=DEFAULT_FEATURE_SET,
                       check_orthonormality=True, check_digest=True):
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

    # Orthonormality, checked because two archived matrices are not bases at
    # all: matrix_ms_reduced.csv and matrix_ms_reduced_old.csv have column
    # norms from 0.03 to 1.0. Projections onto their scaled-down columns
    # shrink 5-30x, distances collapse, and the score comes out wrong while
    # looking entirely plausible -- healthy controls read 118 through one of
    # them and 97.6 through the other. Shape checks cannot see this.
    column_norms = np.linalg.norm(matrix, axis=1)
    gram_error = float(np.abs(matrix @ matrix.T - np.eye(matrix.shape[0])).max())
    if check_orthonormality and gram_error > ORTHONORMALITY_TOLERANCE:
        raise ValueError(
            f"{feature_set.matrix_filename} is not an orthonormal basis: its "
            f"rows depart from orthonormality by {gram_error:.3g} (tolerance "
            f"{ORTHONORMALITY_TOLERANCE}), with norms spanning "
            f"{column_norms.min():.3g} to {column_norms.max():.3g}. GDI's "
            "distance is only meaningful through an orthonormal projection; a "
            "rescaled basis shrinks distances and inflates every score without "
            "failing any shape check. Regenerate it with gdi_reference.py, or "
            "pass check_orthonormality=False if you specifically intend to "
            "reproduce a historic result."
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

    # Which cohort this basis came from. Orthonormality and shape both pass on
    # a well-formed basis built from the wrong control sample, so neither check
    # above can see the archived/regenerated confusion -- the archived gdi9
    # basis scores healthy controls at 100.8 and the archived reduced4 basis at
    # 96.6 when paired with the constants below. Both look normal. Both are
    # wrong. The digest is the only thing that distinguishes them.
    digest = reference_digest(matrix, control_mean)
    if check_digest and feature_set.reference_digest is not None \
            and digest != feature_set.reference_digest:
        raise GdiReferenceMismatchError(
            f"the reference in {directory} is not the one feature set "
            f"{feature_set.name!r} is calibrated against: expected digest "
            f"{feature_set.reference_digest[:16]}..., got {digest[:16]}.... The "
            f"matrix loaded cleanly and is a valid {matrix.shape[0]}-component "
            "orthonormal basis, so nothing else here can catch this -- but "
            f"ln_control_mean={feature_set.ln_control_mean} / "
            f"ln_control_sd={feature_set.ln_control_sd} were derived through a "
            "different one, and using them together shifts every score by an "
            "unknown amount while still looking plausible. Regenerate the "
            "constants for this reference with gdi_reference.py, or pass "
            "check_digest=False if you specifically intend to reproduce a "
            "historic result."
        )

    return {
        "matrix": matrix,
        "control_mean": control_mean,
        "feature_set": feature_set,
        "digest": digest,
        # False when the pairing was not verified -- either the feature set
        # carries no expected digest, or the caller opted out. Callers that
        # report a score should say so.
        "digest_verified": bool(
            check_digest and feature_set.reference_digest is not None),
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

    # Second of the two hard stops. `get_feature_set` above catches a disabled
    # set requested by name (the CLI path); this catches it passed as an
    # object, which duck-typing lets through. Scoring is the last point where
    # refusing still prevents a wrong number from existing.
    if feature_set.is_disabled:
        raise GdiFeatureSetDisabledError(
            f"GDI feature set {feature_set.name!r} is disabled and cannot be "
            f"scored with. {feature_set.disabled_reason}"
        )

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


def gdi_for_side(curves, side, reference, feature_set=None):
    """GDI for one side of one trial, computed on the calibrated unit.

    `curves` is one side's gait-analysis result -- `curves['indiv']`, a list of
    101-point normalised cycles, and `curves['mean']`, their average.

    Under `scoring_unit == "cycle"` (every shipped feature set) each cycle is
    scored and the *scores* are averaged, which is both what the reference is
    calibrated for and what the supervisor's original script did
    (`GDI_r.mean()`). This function previously scored `curves['mean']`
    unconditionally, which read high on every trial -- see SCORING_UNIT_CYCLE
    above for the measured size, and docs/2026-08-31-gdi-vs-ucm-audit.md
    section 3 for why the two are not interchangeable.
    """
    if feature_set is None:
        feature_set = reference.get("feature_set", DEFAULT_FEATURE_SET)
    feature_set = get_feature_set(feature_set)
    unit = getattr(feature_set, "scoring_unit", SCORING_UNIT_CYCLE)

    if unit == SCORING_UNIT_MEAN_CURVE:
        vector = build_gdi_feature_vector(curves["mean"], side, feature_set)
        return compute_gdi(vector, reference, feature_set)

    if unit != SCORING_UNIT_CYCLE:
        raise ValueError(
            f"feature set {feature_set.name!r} declares scoring_unit "
            f"{unit!r}; expected one of {list(SCORING_UNITS)}."
        )

    cycles = curves.get("indiv")
    if not cycles:
        # Deliberately not falling back to curves['mean']. That fallback is
        # exactly the defect being fixed: it returns a number, the number is
        # always too high, and nothing downstream can tell it apart from a
        # correctly-computed one.
        raise KeyError(
            f"feature set {feature_set.name!r} is calibrated per gait cycle "
            f"({feature_set.ln_control_mean} / {feature_set.ln_control_sd} are "
            "moments of the control cohort's per-cycle log distances), but "
            "these curves carry no 'indiv' cycles to score. Pass the full "
            "gait-analysis result, or use a feature set whose scoring_unit is "
            f"{SCORING_UNIT_MEAN_CURVE!r}."
        )

    scores = [
        compute_gdi(build_gdi_feature_vector(cycle, side, feature_set),
                    reference, feature_set)
        for cycle in cycles
    ]
    return float(np.mean(scores))


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
        scores[side] = gdi_for_side(results[key], side, reference, feature_set)
    scores["average"] = (scores["r"] + scores["l"]) / 2.0
    return scores
