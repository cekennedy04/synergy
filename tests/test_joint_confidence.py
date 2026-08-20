"""
Tests U3 of the clinician trial report GUI plan: joint_confidence.py's
per-segment confidence indicator (R9, KTD5, KTD7).

All synthetic data -- no real .mvnx/.mot files, no OpenSim, no real patient
data. `joint_angles`/`times` mirror the exact shape
`xsens_to_opensim.parse_mvnx()` returns (a list of per-frame lists of
(abduction_adduction, internal_external_rotation, flexion_extension)
tuples, or None for a frame with no <jointAngle> data); `mot_coordinates`/
`mot_times` mirror a parsed .mot file (dict of coordinate name -> per-frame
values, plus a shared time vector).

Follows this repo's test convention (see tests/test_clinician_gui_pipeline.py,
tests/test_xsens_to_opensim_source_selection.py): load the module under
test via importlib.util.spec_from_file_location against an absolute path,
rather than a plain `import joint_confidence`.
"""
import importlib.util
import os

import numpy as np
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MODULE_PATH = os.path.join(REPO_ROOT, 'joint_confidence.py')


def _load_module():
    spec = importlib.util.spec_from_file_location('joint_confidence_under_test', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def jc():
    return _load_module()


def _make_frame(jc, segment_name, dof_name, value):
    """One synthetic <jointAngle> frame: all-zero for every joint except
    `segment_name`'s `dof_name` DOF, set to `value` -- mirrors
    parse_mvnx()'s per-frame shape (a list of (add/abd, int/ext, flex/ext)
    tuples in STANDARD_22_JOINT_ORDER order)."""
    joint_index = jc.STANDARD_22_JOINT_ORDER.index(segment_name)
    dof_index = jc.JOINT_ANGLE_DOF_NAMES.index(dof_name)
    frame = [(0.0, 0.0, 0.0)] * len(jc.STANDARD_22_JOINT_ORDER)
    values = [0.0, 0.0, 0.0]
    values[dof_index] = value
    frame[joint_index] = tuple(values)
    return frame


def _make_series(jc, segment_name, dof_name, times, value_fn):
    joint_angles = [_make_frame(jc, segment_name, dof_name, value_fn(t)) for t in times]
    return joint_angles, list(times)


def test_close_agreement_scores_high_confidence(jc):
    times = np.linspace(0.0, 5.0, 200)

    def angle(t):
        return 20.0 + 10.0 * np.sin(t)

    joint_angles, xsens_times = _make_series(jc, "jRightKnee", "flexion_extension", times, angle)
    # Same time base, tiny noise -- should agree closely.
    rng = np.random.default_rng(0)
    mot_values = angle(times) + rng.normal(0.0, 0.2, size=len(times))
    mot_coordinates = {"knee_angle_r": mot_values}

    result = jc.score_confidence(joint_angles, xsens_times, mot_coordinates, times)

    assert result["available"] is True
    segment = result["segments"]["jRightKnee"]
    assert segment["status"] == "scored"
    assert segment["tier"] == "high"
    assert segment["rms_deg"] <= jc.TIER_HIGH_MAX_RMS_DEG


def test_large_sustained_divergence_scores_low_confidence(jc):
    times = np.linspace(0.0, 5.0, 200)

    def xsens_angle(t):
        return 20.0 + 10.0 * np.sin(t)

    def mot_angle(t):
        # Large, sustained offset -- mirrors the real femur/tibia finding
        # (AE3): not a brief spike, a persistent divergence across the trial.
        return xsens_angle(t) + 35.0

    joint_angles, xsens_times = _make_series(jc, "jRightKnee", "flexion_extension", times, xsens_angle)
    mot_coordinates = {"knee_angle_r": mot_angle(times)}

    result = jc.score_confidence(joint_angles, xsens_times, mot_coordinates, times)

    segment = result["segments"]["jRightKnee"]
    assert segment["status"] == "scored"
    assert segment["tier"] == "low"
    assert segment["rms_deg"] > jc.TIER_MEDIUM_MAX_RMS_DEG


def test_resampling_aligns_different_sample_rates_to_same_tier_as_shared_time_base(jc):
    """Proves KTD7's timestamp alignment, not just the scoring math: the
    two series are sampled at very different rates/offsets from the same
    underlying function, so a naive index-by-index comparison (ignoring
    timestamps) would compare wildly different phase points and report a
    spuriously large divergence -- but score_confidence's actual timestamp-
    based resampling should recover close agreement (a "high" tier), the
    same tier as if both series had shared one dense time base.
    """
    def angle(t):
        return 15.0 + 12.0 * np.sin(2.0 * np.pi * t / 2.0)  # 2s period

    # Xsens: coarse, 26 samples over 5s (dt=0.2s).
    xsens_times = np.linspace(0.0, 5.0, 26)
    joint_angles, xsens_times = _make_series(jc, "jLeftHip", "flexion_extension", xsens_times, angle)

    # .mot: dense, 501 samples over 5s (dt=0.01s) -- very different rate.
    mot_times = np.linspace(0.0, 5.0, 501)
    mot_coordinates = {"hip_flexion_l": angle(mot_times)}

    result = jc.score_confidence(joint_angles, xsens_times, mot_coordinates, mot_times)
    segment = result["segments"]["jLeftHip"]
    assert segment["status"] == "scored"
    assert segment["tier"] == "high"

    # Sanity check that alignment, not luck, produced this: a naive
    # index-by-index comparison over the shorter series' length would NOT
    # correspond to matching time instants (xsens_times[25] == 5.0s but
    # mot_times[25] == 0.25s), so it reports a materially worse (different
    # tier) agreement than proper timestamp-based alignment does.
    n = len(xsens_times)
    xsens_values = np.array([frame[jc.STANDARD_22_JOINT_ORDER.index("jLeftHip")][2] for frame in joint_angles])
    naive_mot_values = np.asarray(mot_coordinates["hip_flexion_l"])[:n]
    naive_rms = float(np.sqrt(np.mean((xsens_values - naive_mot_values) ** 2)))
    assert segment["rms_deg"] < naive_rms
    assert jc._classify_tier(naive_rms) != segment["tier"]

    # Compare against a shared-time-base version of the same underlying
    # function, to confirm the resulting tier matches.
    shared_times_arr = np.linspace(0.0, 5.0, 300)
    shared_joint_angles, shared_times = _make_series(
        jc, "jLeftHip", "flexion_extension", shared_times_arr, angle
    )
    shared_result = jc.score_confidence(
        shared_joint_angles, shared_times, {"hip_flexion_l": angle(shared_times_arr)}, shared_times
    )
    assert shared_result["segments"]["jLeftHip"]["tier"] == segment["tier"] == "high"


def test_unmapped_segment_is_reported_as_not_scored(jc):
    times = np.linspace(0.0, 2.0, 50)
    joint_angles, xsens_times = _make_series(
        jc, "jT9T8", "flexion_extension", times, lambda t: 5.0
    )
    # No mapping entry exists for "jT9T8" in XSENS_TO_MOT_COORDINATE, and no
    # matching .mot coordinate is supplied either.
    result = jc.score_confidence(joint_angles, xsens_times, {}, times, segment_names=["jT9T8"])

    assert result["available"] is True
    segment = result["segments"]["jT9T8"]
    assert segment["status"] == "not_scored"
    assert segment["reason"]
    assert segment["tier"] is None


def test_no_joint_angle_data_anywhere_reports_confidence_unavailable(jc):
    times = list(np.linspace(0.0, 3.0, 30))
    joint_angles = [None] * len(times)
    mot_coordinates = {"knee_angle_r": np.zeros(30)}

    result = jc.score_confidence(joint_angles, times, mot_coordinates, times)

    assert result["available"] is False
    assert result["reason"]
    assert result["segments"] == {}
