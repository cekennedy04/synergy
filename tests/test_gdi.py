"""Tests for gdi.py -- the Gait Deviation Index recovered from commit 3a568fb
and repaired (see that module's docstring for the bug list).

Reference data is synthetic throughout. The real normative control dataset is
not in this repo, and would not belong in a test fixture even if it were: what
these pin is the *arithmetic and the guardrails*, which are checkable without
it. A synthetic matrix of known shape exercises the same code path.
"""
import csv
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "gdi.py"


@pytest.fixture(scope="module")
def gdi():
    spec = importlib.util.spec_from_file_location("gdi_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_reference(directory, n_components=15, vector_length=459, control=None):
    """Write a synthetic reference pair with the real filenames."""
    directory = Path(directory)
    matrix = np.arange(n_components * vector_length, dtype=float).reshape(
        n_components, vector_length
    ) / (n_components * vector_length)
    # load_gdi_reference transposes on load, so write the transpose.
    with open(directory / "matrix_ms_reduced.csv", "w", newline="") as handle:
        csv.writer(handle).writerows(matrix.T)
    control = np.zeros(n_components) if control is None else control
    with open(directory / "controlCalc_ms_reduced.csv", "w", newline="") as handle:
        csv.writer(handle).writerow(control)
    return matrix


def _mean_curves(side, value=1.0):
    """101-point flat curves for all 9 GDI coordinates on one side."""
    names = [
        "pelvis_tilt", "pelvis_list", "pelvis_rotation",
        f"hip_flexion_{side}", f"hip_adduction_{side}", f"hip_rotation_{side}",
        f"knee_angle_{side}", f"ankle_angle_{side}", f"subtalar_angle_{side}",
    ]
    return {name: [value] * 101 for name in names}


# -- shape of the feature vector ----------------------------------------


def test_feature_vector_is_nine_variables_by_fiftyone_points(gdi):
    """The bug that motivated this rewrite: the original's right-leg path
    built 36 coordinates x 101 points (3636 values) with the downsampling
    commented out, while GDI is defined on 9 x 51 = 459."""
    vector = gdi.build_gdi_feature_vector(_mean_curves("r"), "r")

    assert gdi.GDI_N_FEATURES == 9
    assert gdi.GDI_N_POINTS == 51
    assert vector.shape == (459,)


def test_cycle_is_sampled_every_other_point(gdi):
    """51 points means frames 0, 2, 4 ... 100 -- the original's
    `if (num % 2 == 0)`, which was live on the left side and commented out on
    the right."""
    assert gdi.GDI_CYCLE_POINTS[:3] == (0, 2, 4)
    assert gdi.GDI_CYCLE_POINTS[-1] == 100
    assert len(set(gdi.GDI_CYCLE_POINTS)) == 51


def test_pelvis_tilt_offset_and_rotation_wrap_are_preserved(gdi):
    """Two per-coordinate adjustments carried over verbatim; changing either
    silently shifts every score."""
    curves = _mean_curves("r", value=0.0)
    curves["pelvis_tilt"] = [5.0] * 101
    curves["pelvis_rotation"] = [200.0] * 101

    vector = gdi.build_gdi_feature_vector(curves, "r")

    assert vector[0] == pytest.approx(25.0)                    # 5 + 20
    assert vector[2 * 51] == pytest.approx(20.0)               # 200 - 180


def test_rotation_below_threshold_is_not_wrapped(gdi):
    curves = _mean_curves("r", value=0.0)
    curves["pelvis_rotation"] = [179.0] * 101

    vector = gdi.build_gdi_feature_vector(curves, "r")

    assert vector[2 * 51] == pytest.approx(179.0)


def test_both_sides_use_their_own_joint_names(gdi):
    assert "knee_angle_r" in gdi.gdi_features("r")
    assert "knee_angle_l" in gdi.gdi_features("l")
    # pelvis terms are shared, not sided
    assert gdi.gdi_features("r")[:3] == gdi.gdi_features("l")[:3]


def test_missing_gdi_coordinate_names_the_gap(gdi):
    curves = _mean_curves("r")
    del curves["subtalar_angle_r"]

    with pytest.raises(KeyError, match="subtalar_angle_r"):
        gdi.build_gdi_feature_vector(curves, "r")


def test_short_curve_is_rejected_rather_than_silently_sampled(gdi):
    curves = _mean_curves("r")
    curves["knee_angle_r"] = [1.0] * 40

    with pytest.raises(ValueError, match="101-point"):
        gdi.build_gdi_feature_vector(curves, "r")


# -- reference loading, and the filename bug ----------------------------


def test_missing_reference_raises_a_named_actionable_error(gdi, tmp_path):
    """Bug 1/2 in the original: it checked for matrix.csv but opened
    matrix_ms_reduced.csv, so a half-populated directory either crashed with
    FileNotFoundError or skipped silently and hit a NameError much later."""
    with pytest.raises(gdi.GdiReferenceMissingError) as caught:
        gdi.load_gdi_reference(tmp_path)

    message = str(caught.value)
    assert "matrix_ms_reduced.csv" in message
    assert "controlCalc_ms_reduced.csv" in message
    assert "normative control group" in message


def test_half_populated_reference_directory_still_raises(gdi, tmp_path):
    """The exact shape of the original bug: one file present, one absent."""
    _write_reference(tmp_path)
    (tmp_path / "controlCalc_ms_reduced.csv").unlink()

    with pytest.raises(gdi.GdiReferenceMissingError, match="controlCalc_ms_reduced.csv"):
        gdi.load_gdi_reference(tmp_path)


def test_reference_dimension_disagreement_is_caught_at_load(gdi, tmp_path):
    _write_reference(tmp_path, n_components=15)
    with open(tmp_path / "controlCalc_ms_reduced.csv", "w", newline="") as handle:
        csv.writer(handle).writerow(np.zeros(9))

    with pytest.raises(ValueError, match="same control dataset"):
        gdi.load_gdi_reference(tmp_path)


def test_reference_loads_and_is_transposed(gdi, tmp_path):
    _write_reference(tmp_path, n_components=15, vector_length=459)

    reference = gdi.load_gdi_reference(tmp_path)

    assert reference["matrix"].shape == (15, 459)
    assert reference["control_mean"].shape == (15,)


# -- the score itself ----------------------------------------------------


def test_subject_matching_the_control_mean_scores_exactly_100(gdi, tmp_path):
    """GDI's definition: 100 is the control mean. Also guards log(0)."""
    matrix = _write_reference(tmp_path, n_components=15)
    vector = gdi.build_gdi_feature_vector(_mean_curves("r"), "r")
    reference = gdi.load_gdi_reference(tmp_path)
    reference["control_mean"] = reference["matrix"] @ vector

    assert gdi.compute_gdi(vector, reference) == pytest.approx(100.0)


def test_score_follows_the_published_formula(gdi, tmp_path):
    """Pins GDI = 100 - 10 * (ln(distance) - mean) / sd against an
    independently computed expectation."""
    _write_reference(tmp_path, n_components=15)
    reference = gdi.load_gdi_reference(tmp_path)
    vector = gdi.build_gdi_feature_vector(_mean_curves("r", value=2.0), "r")

    subject = reference["matrix"] @ vector
    diff = subject - reference["control_mean"]
    expected_z = (math.log(math.sqrt(float(np.sum(np.square(diff)))))
                  - gdi.LN_CONTROL_MEAN) / gdi.LN_CONTROL_SD
    expected = 100.0 - 10.0 * expected_z

    assert gdi.compute_gdi(vector, reference) == pytest.approx(expected)


def test_ten_points_is_one_standard_deviation(gdi):
    """The clinical interpretation the score exists to support."""
    assert gdi.LN_CONTROL_SD > 0
    # a subject one SD further away in log-distance scores 10 points lower
    assert 100.0 - 10.0 * 1.0 == 90.0


def test_wrong_length_vector_is_rejected_with_both_numbers(gdi, tmp_path):
    """Bug 5: a shape mismatch previously surfaced as an opaque numpy error
    with no indication of which side was wrong."""
    _write_reference(tmp_path, n_components=15, vector_length=459)
    reference = gdi.load_gdi_reference(tmp_path)

    with pytest.raises(ValueError, match="459"):
        gdi.compute_gdi(np.ones(100), reference)


def test_gdi_for_trial_scores_both_sides_and_averages(gdi, tmp_path):
    _write_reference(tmp_path, n_components=15)
    reference = gdi.load_gdi_reference(tmp_path)
    results = {
        "curves_r": {"mean": _mean_curves("r", value=2.0)},
        "curves_l": {"mean": _mean_curves("l", value=3.0)},
    }

    scores = gdi.gdi_for_trial(results, reference)

    assert set(scores) == {"r", "l", "average"}
    assert scores["average"] == pytest.approx((scores["r"] + scores["l"]) / 2)


def test_gdi_features_exclude_translations_and_com(gdi):
    """Why GDI is usable on this project's IMU data at all: none of its 9
    variables is a translation or centre-of-mass term, so the pinned-root
    limitation that invalidates gait_speed/stride_length does not touch it."""
    for side in ("r", "l"):
        for name in gdi.gdi_features(side):
            assert not name.startswith("com")
            assert not name.startswith("pelvis_t") or name == "pelvis_tilt"
