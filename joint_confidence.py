"""
joint_confidence.py

Per-segment confidence indicator for a converted Xsens trial (Product
Contract R9 / Planning Contract KTD5, KTD7; Implementation Unit U3).

WHAT THIS ACTUALLY MEASURES -- READ BEFORE SURFACING ANY RESULT FROM THIS
MODULE TO A CLINICIAN
---------------------------------------------------------------------------
This module compares two DERIVED estimates against each other:

  1. The Xsens suit's own onboard `<jointAngle>` estimate (extracted by
     `xsens_to_opensim.parse_mvnx()`, computed by Xsens's own proprietary
     fusion algorithm from the same IMU data), and
  2. This pipeline's own OpenSim IMUInverseKinematicsTool output (the
     `.mot` file's coordinate values), which is calibrated off a single
     static pose and independently derived from the same raw IMU
     orientations.

Close agreement between the two is evidence they're both measuring the same
real motion; large divergence is evidence at least one of them is wrong
(and VENDORING.md's own validation work suggests it is usually this
pipeline's own IMU-IK stage, worst for femur/tibia, far from the static
calibration pose -- see the "calibration concern, quantified" section).

Neither series is ground truth. **A "high" tier here means "this pipeline's
angle agrees closely with the suit's own onboard estimate" -- it is NOT a
claim of clinical/anatomical accuracy against any independent reference.**
Callers (U4's display layer) must keep that framing in the label text they
show a clinician; this module only computes the number and the tier, not
the clinician-facing copy.

WHAT THIS MODULE DOES NOT DO
---------------------------------------------------------------------------
No file I/O, no tkinter, no OpenSim import, no `Examples/gaitAnalysis-UCM.py`
import (that file `os.chdir()`s the process and needs `opensim` merely to be
imported for other reasons -- pulling it in here would be the wrong
dependency direction; KTD5 explicitly calls for duplicating its relevant
`JOINT_NAMES` entries instead). Every public function here is a pure
function over plain Python/numpy data structures, matching the shape
`xsens_to_opensim.parse_mvnx()` and this pipeline's own `.mot` output
already produce, so it can be unit-tested with synthetic arrays alone.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Duplicated constants (per KTD5: duplicate, don't import at runtime).
# ---------------------------------------------------------------------------

# Duplicated from xsens_to_opensim.py's STANDARD_22_JOINT_ORDER (as of
# 2026-08-19, lines 206-212). Xsens's own full-body 22-joint order for the
# <jointAngle> element (66 values/frame = 22 joints x 3 DOF). Kept as our
# own copy, not an `import xsens_to_opensim`, so this module has zero
# runtime dependency on that file (which itself has no OpenSim import at
# module level today, but this module is meant to stay independently
# testable regardless of that file's future changes) -- re-sync by hand if
# xsens_to_opensim.py's own copy of this list ever changes.
STANDARD_22_JOINT_ORDER = [
    "jL5S1", "jL4L3", "jL1T12", "jT9T8", "jT1C7", "jC1Head",
    "jRightC7Shoulder", "jRightShoulder", "jRightElbow", "jRightWrist",
    "jLeftC7Shoulder", "jLeftShoulder", "jLeftElbow", "jLeftWrist",
    "jRightHip", "jRightKnee", "jRightAnkle", "jRightBallFoot",
    "jLeftHip", "jLeftKnee", "jLeftAnkle", "jLeftBallFoot",
]

# Duplicated from xsens_to_opensim.py's JOINT_ANGLE_DOF_NAMES (as of
# 2026-08-19, lines 221-223). The 3 values per joint in <jointAngle>, in
# order -- flexion/extension is the THIRD value, not the first, for every
# joint (confirmed there against context/S01-001.xlsx's real column
# headers).
JOINT_ANGLE_DOF_NAMES = (
    "abduction_adduction", "internal_external_rotation", "flexion_extension",
)

# Duplicated (not imported) from Examples/gaitAnalysis-UCM.py's JOINT_NAMES
# constant (as of 2026-08-20, lines 133-141) -- see module docstring and
# KTD5 for why this is a copy, not an import. Only the entries this
# module's XSENS_TO_MOT_COORDINATE mapping actually uses are reproduced
# here; re-sync by hand if gaitAnalysis-UCM.py's JOINT_NAMES ever changes
# these specific coordinate names.
MOT_COORDINATE_NAMES_USED = [
    "lumbar_extension",
    "hip_flexion_r", "knee_angle_r", "ankle_angle_r",
    "hip_flexion_l", "knee_angle_l", "ankle_angle_l",
    "elbow_flex_r", "elbow_flex_l",
]

# ---------------------------------------------------------------------------
# Xsens joint -> OpenSim .mot coordinate mapping (KTD5's Approach step 1).
# ---------------------------------------------------------------------------
#
# Each value is (mot_coordinate_name, dof_name), where dof_name is one of
# JOINT_ANGLE_DOF_NAMES's three entries -- the single Xsens DOF that
# corresponds to that (single-DOF, hinge-like) OpenSim coordinate. Most
# gait/limb coordinates in MOT_COORDINATE_NAMES_USED are flexion-only, so
# "flexion_extension" (JOINT_ANGLE_DOF_NAMES[2]) is what's picked for all of
# them here; hip_adduction_r/hip_rotation_r etc. exist as separate OpenSim
# coordinates but are deliberately left unmapped rather than guessed at,
# same as every Xsens joint not listed below (e.g. wrists, shoulders, the
# thoracic/cervical spine joints, ball-of-foot) -- score_confidence() reports
# those as "not_scored" rather than omitting or crashing on them (U3's
# Approach step 5).
#
# jL5S1 (the lumbosacral joint) stands in for the torso/pelvis region --
# VENDORING.md's real per-segment error table found torso_imu/pelvis_imu
# (the calibration reference itself) tracking far better than the legs, so
# this is the mapped segment expected to land in the "high" tier most
# often; jRightKnee/jRightHip/jLeftKnee/jLeftHip (via femur/tibia) are the
# ones expected to land in "low" per that same table (AE3).
XSENS_TO_MOT_COORDINATE = {
    "jL5S1": ("lumbar_extension", "flexion_extension"),
    "jRightHip": ("hip_flexion_r", "flexion_extension"),
    "jRightKnee": ("knee_angle_r", "flexion_extension"),
    "jRightAnkle": ("ankle_angle_r", "flexion_extension"),
    "jLeftHip": ("hip_flexion_l", "flexion_extension"),
    "jLeftKnee": ("knee_angle_l", "flexion_extension"),
    "jLeftAnkle": ("ankle_angle_l", "flexion_extension"),
    "jRightElbow": ("elbow_flex_r", "flexion_extension"),
    "jLeftElbow": ("elbow_flex_l", "flexion_extension"),
}

# ---------------------------------------------------------------------------
# Tiering thresholds -- PROVISIONAL, per KTD5/U3 Approach step 4.
# ---------------------------------------------------------------------------
#
# Grounded loosely in VENDORING.md's "calibration concern, quantified" /
# full-43s-trial per-segment orientation-error table (torso_imu: 0.1 deg
# RMS; pelvis_imu: 7.8 deg RMS; tibia/femur: 24-32 deg RMS), NOT a direct
# fit -- that table is IMU-ORIENTATION RMS error against a different
# reference than what this module computes (onboard-jointAngle-vs-.mot
# ANGLE difference), so the two numbers are related but not identical (see
# KTD5's own note on this). Treat these cutoffs as tunable once real trials
# let us check whether the tiering actually tracks real leg-tracking
# quality, not as a validated clinical threshold.
TIER_HIGH_MAX_RMS_DEG = 8.0     # >= torso/pelvis-like agreement
TIER_MEDIUM_MAX_RMS_DEG = 20.0  # between torso/pelvis and femur/tibia-like
# > TIER_MEDIUM_MAX_RMS_DEG => "low" (femur/tibia-like agreement)

# Minimum number of aligned samples (after KTD7's timestamp resampling) a
# segment needs before its score means anything -- an assumption
# documented in the plan's Assumptions section, not derived from data.
# Below this, report "not_scored" rather than a numerically-real but
# practically-meaningless tier from a handful of points.
MIN_ALIGNED_SAMPLES = 5


def _has_any_joint_angle_data(joint_angles):
    """True if at least one frame has real <jointAngle> data.

    Mirrors parse_mvnx()'s own representation: `joint_angles` is a list,
    one entry per motion frame, each either a list of
    len(STANDARD_22_JOINT_ORDER) (add/abd, int/ext, flex/ext) tuples, or
    None for a frame with no <jointAngle> element at all. A file that
    never carries this element at all (a real, documented case -- not
    every .mvnx export includes it) has every entry None.
    """
    return any(frame is not None for frame in joint_angles)


def _not_scored(reason):
    return {
        "status": "not_scored",
        "reason": reason,
        "coordinate_name": None,
        "rms_deg": None,
        "n_aligned_samples": None,
        "tier": None,
    }


def _classify_tier(rms_deg):
    if rms_deg <= TIER_HIGH_MAX_RMS_DEG:
        return "high"
    if rms_deg <= TIER_MEDIUM_MAX_RMS_DEG:
        return "medium"
    return "low"


def _resample_to_common_grid(times_a, values_a, times_b, values_b):
    """KTD7's alignment step: resample the lower-rate series onto the
    higher-rate series's own timestamps via linear interpolation
    (`numpy.interp`), restricted to the time range both series actually
    cover (no extrapolation past either series' real data).

    Returns (aligned_a, aligned_b, n_aligned) as numpy arrays / int. Both
    outputs share the same length and correspond 1:1 in time, regardless
    of the two inputs' original sample rates or offsets.
    """
    times_a = np.asarray(times_a, dtype=float)
    values_a = np.asarray(values_a, dtype=float)
    times_b = np.asarray(times_b, dtype=float)
    values_b = np.asarray(values_b, dtype=float)

    order_a = np.argsort(times_a)
    times_a, values_a = times_a[order_a], values_a[order_a]
    order_b = np.argsort(times_b)
    times_b, values_b = times_b[order_b], values_b[order_b]

    overlap_start = max(times_a[0], times_b[0])
    overlap_end = min(times_a[-1], times_b[-1])
    if overlap_end <= overlap_start:
        return np.array([]), np.array([]), 0

    # Resample onto whichever series has more samples (a proxy for "higher
    # rate" that also works when the two series merely cover different
    # durations), restricted to the overlapping time window.
    if len(times_a) >= len(times_b):
        target_times = times_a[(times_a >= overlap_start) & (times_a <= overlap_end)]
    else:
        target_times = times_b[(times_b >= overlap_start) & (times_b <= overlap_end)]

    aligned_a = np.interp(target_times, times_a, values_a)
    aligned_b = np.interp(target_times, times_b, values_b)
    return aligned_a, aligned_b, len(target_times)


def _score_one_segment(segment_name, joint_angles, times, mot_coordinates, mot_times):
    mapping_entry = XSENS_TO_MOT_COORDINATE.get(segment_name)
    if mapping_entry is None:
        return _not_scored(
            f"No OpenSim coordinate mapping is defined for '{segment_name}'."
        )

    coordinate_name, dof_name = mapping_entry
    if coordinate_name not in mot_coordinates:
        return _not_scored(
            f"'{coordinate_name}' is not present in this run's .mot output."
        )

    dof_index = JOINT_ANGLE_DOF_NAMES.index(dof_name)
    joint_index = STANDARD_22_JOINT_ORDER.index(segment_name)

    xsens_times = []
    xsens_values = []
    for t, frame in zip(times, joint_angles):
        if frame is None:
            continue
        xsens_times.append(t)
        xsens_values.append(frame[joint_index][dof_index])

    mot_values = list(mot_coordinates[coordinate_name])
    mot_times_list = list(mot_times)

    if len(xsens_times) < 2 or len(mot_times_list) < 2:
        return _not_scored(
            "Not enough samples in one of the two series to align by time."
        )

    aligned_xsens, aligned_mot, n_aligned = _resample_to_common_grid(
        xsens_times, xsens_values, mot_times_list, mot_values,
    )

    if n_aligned < MIN_ALIGNED_SAMPLES:
        return _not_scored(
            f"Only {n_aligned} aligned sample(s) after time-base alignment "
            f"(need at least {MIN_ALIGNED_SAMPLES}) -- too few to score "
            "meaningfully."
        )

    # RMS, not mean absolute difference: VENDORING.md's own past validation
    # study (the per-segment orientation-error table this tiering is
    # grounded in) reports RMS, and RMS is more sensitive to a large,
    # sustained divergence than MAE -- the failure mode this indicator
    # exists to catch (AE3's femur/tibia case) -- so it's the more
    # consistent and more conservative choice here.
    diffs = aligned_xsens - aligned_mot
    rms_deg = float(np.sqrt(np.mean(diffs ** 2)))

    return {
        "status": "scored",
        "reason": None,
        "coordinate_name": coordinate_name,
        "rms_deg": rms_deg,
        "n_aligned_samples": int(n_aligned),
        "tier": _classify_tier(rms_deg),
    }


def score_confidence(joint_angles, times, mot_coordinates, mot_times, segment_names=None):
    """Score per-segment agreement between the suit's own onboard
    `<jointAngle>` estimate and this pipeline's `.mot` output.

    Args:
        joint_angles: `parse_mvnx(mvnx_path)["joint_angles"]` -- a list, one
            entry per motion frame, each either a list of
            len(STANDARD_22_JOINT_ORDER) (abduction_adduction,
            internal_external_rotation, flexion_extension) tuples in
            degrees, or None for a frame with no <jointAngle> data.
        times: `parse_mvnx(mvnx_path)["times"]` -- one float (seconds) per
            entry in `joint_angles`, same length/order.
        mot_coordinates: dict mapping an OpenSim .mot coordinate name
            (e.g. "knee_angle_r") to a sequence of per-frame values in
            degrees, one per entry in `mot_times`.
        mot_times: sequence of floats (seconds), one per row of the .mot
            output, shared across every entry in `mot_coordinates`.
        segment_names: which Xsens joint names (STANDARD_22_JOINT_ORDER
            entries) to report on. Defaults to all of
            STANDARD_22_JOINT_ORDER, so every segment -- mapped or not --
            gets an explicit entry in the result rather than being silently
            omitted (U3 Approach step 5).

    Returns a dict:
        {
            "available": bool,
            "reason": str | None,  # set when `available` is False
            "segments": {
                segment_name: {
                    "status": "scored" | "not_scored",
                    "reason": str | None,        # set when not scored
                    "coordinate_name": str | None,
                    "rms_deg": float | None,
                    "n_aligned_samples": int | None,
                    "tier": "high" | "medium" | "low" | None,
                },
                ...
            },
        }

    If `joint_angles` has no data for any frame at all (a real, documented
    .mvnx shape -- see `_has_any_joint_angle_data`), returns
    `{"available": False, "reason": ..., "segments": {}}` instead of
    attempting per-segment scoring (U3 Approach step 2 / R9's no-data
    fallback) -- never an empty-but-implicitly-"fine" per-segment
    breakdown.

    See the module docstring for what "high" actually means here: agreement
    with the suit's own onboard estimate, not ground-truth accuracy.
    """
    if not _has_any_joint_angle_data(joint_angles):
        return {
            "available": False,
            "reason": (
                "This recording's .mvnx has no onboard <jointAngle> data "
                "for any frame, so no comparison against the suit's own "
                "estimate is possible for this trial."
            ),
            "segments": {},
        }

    if segment_names is None:
        segment_names = list(STANDARD_22_JOINT_ORDER)

    segments = {
        segment_name: _score_one_segment(
            segment_name, joint_angles, times, mot_coordinates, mot_times
        )
        for segment_name in segment_names
    }

    return {"available": True, "reason": None, "segments": segments}
