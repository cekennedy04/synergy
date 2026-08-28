"""Tests for gdi.py -- the Gait Deviation Index, recovered from commit 3a568fb,
repaired 2026-08-25, and parameterised by feature set 2026-08-27.

Reference data is synthetic throughout. The real normative control dataset is
not in this repo, and would not belong in a test fixture even if it were: what
these pin is the *arithmetic, the feature-set bookkeeping, and the guardrails*,
which are checkable without it.
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


@pytest.fixture
def scoring_set(gdi):
    """The canonical nine variables, but with normative constants attached.

    GDI9 deliberately ships without constants (none could be attributed from
    the recovered code), so the arithmetic tests need a set that can score.
    Using the canonical variable list keeps the 9-variable curve helper below
    usable for both.
    """
    return gdi.GdiFeatureSet(
        name="test9",
        features=gdi.GDI9.features,
        matrix_filename="matrix_test.csv",
        control_filename="controlcalc_test.csv",
        ln_control_mean=4.5,
        ln_control_sd=0.4,
    )


def _write_reference(directory, feature_set, n_components=15, control=None,
                     vector_length=None):
    """Write a synthetic reference pair under this feature set's filenames."""
    directory = Path(directory)
    length = feature_set.vector_length if vector_length is None else vector_length
    matrix = np.arange(n_components * length, dtype=float).reshape(
        n_components, length
    ) / (n_components * length)
    # load_gdi_reference transposes on load, so write the transpose.
    with open(directory / feature_set.matrix_filename, "w", newline="") as handle:
        csv.writer(handle).writerows(matrix.T)
    control = np.zeros(n_components) if control is None else control
    with open(directory / feature_set.control_filename, "w", newline="") as handle:
        csv.writer(handle).writerow(control)
    return matrix


def _mean_curves(side, value=1.0, feature_set=None, gdi=None):
    """101-point flat curves for one feature set's coordinates on one side."""
    if feature_set is None:
        names = [
            "pelvis_tilt", "pelvis_list", "pelvis_rotation",
            f"hip_flexion_{side}", f"hip_adduction_{side}", f"hip_rotation_{side}",
            f"knee_angle_{side}", f"ankle_angle_{side}", f"fpa_{side}",
        ]
    else:
        names = list(feature_set.feature_names(side))
    return {name: [value] * 101 for name in names}


# -- the recovered feature sets -------------------------------------------
# Every reduced set was recovered from the archived matrices' row counts and
# the supervisor's slicing code. n_variables x 51 must equal those row counts
# exactly, or the recovery was wrong.


@pytest.mark.parametrize("name,n_features,rows", [
    ("gdi9", 9, 459),
    ("reduced6", 6, 306),
    ("reduced5", 5, 255),
    ("reduced4", 4, 204),
])
def test_each_feature_set_matches_its_archived_matrix_row_count(gdi, name,
                                                                n_features, rows):
    feature_set = gdi.FEATURE_SETS[name]

    assert feature_set.n_features == n_features
    assert feature_set.vector_length == rows


def test_the_six_variable_set_is_the_canonical_nine_minus_pelvis(gdi):
    """Recovered from `indiv_data[153::]` -- rows 153-458 of the 459-row
    vector, which is exactly the six non-pelvis variables."""
    assert gdi.REDUCED6.features == gdi.GDI9.features[3:]
    assert not any("pelvis" in name for name in gdi.REDUCED6.features)


def test_the_ninth_variable_is_fpa_not_subtalar(gdi):
    """The 2026-08-25 recovery picked `subtalar_angle` from one commented
    block of the original while the live supervisor script uses `fpa`. Every
    feature vector built before 2026-08-27 was wrong in its last 51 values."""
    assert gdi.GDI9.features[-1] == "fpa_{side}"
    assert "fpa_r" in gdi.gdi_features("r", gdi.GDI9)
    assert not any("subtalar" in name for name in gdi.GDI9.features)


def test_the_project_default_is_reduced6(gdi):
    """Decided 2026-08-28 from the supervisor's "6 joints instead of 26" note.
    Pinned because scores are not comparable across feature sets, so changing
    this silently changes every number the project reports."""
    assert gdi.DEFAULT_FEATURE_SET is gdi.REDUCED6
    assert gdi.DEFAULT_FEATURE_SET.n_features == 6
    # No pelvis terms, so neither pelvis adjustment can misalign a subject
    # vector against the reference -- see the constant's comment.
    assert not any("pelvis" in name for name in gdi.DEFAULT_FEATURE_SET.features)


def test_an_unknown_feature_set_lists_the_real_ones(gdi):
    with pytest.raises(KeyError, match="reduced6"):
        gdi.get_feature_set("reduced7")


# -- shape of the feature vector ------------------------------------------


def test_feature_vector_length_follows_the_feature_set(gdi):
    """The bug that motivated the rewrite: the original's right-leg path built
    36 coordinates x 101 points with the downsampling commented out. The bug
    that motivated the parameterisation: 9 x 51 was hardcoded while the
    default reference matrix was built for 5 variables."""
    nine = gdi.build_gdi_feature_vector(_mean_curves("r"), "r", gdi.GDI9)
    six = gdi.build_gdi_feature_vector(
        _mean_curves("r", feature_set=gdi.REDUCED6), "r", gdi.REDUCED6)

    assert gdi.GDI_N_POINTS == 51
    assert nine.shape == (459,)
    assert six.shape == (306,)


def test_cycle_is_sampled_every_other_point(gdi):
    """51 points means frames 0, 2, 4 ... 100 -- the original's
    `if (num % 2 == 0)`, live on the left side and commented out on the right."""
    assert gdi.GDI_CYCLE_POINTS[:3] == (0, 2, 4)
    assert gdi.GDI_CYCLE_POINTS[-1] == 100
    assert len(set(gdi.GDI_CYCLE_POINTS)) == 51


def test_pelvis_tilt_offset_and_rotation_wrap_are_preserved(gdi):
    """Two per-coordinate adjustments carried over verbatim; changing either
    silently shifts every score."""
    curves = _mean_curves("r", value=0.0)
    curves["pelvis_tilt"] = [5.0] * 101
    curves["pelvis_rotation"] = [200.0] * 101

    vector = gdi.build_gdi_feature_vector(curves, "r", gdi.GDI9)

    assert vector[0] == pytest.approx(25.0)                    # 5 + 20
    assert vector[2 * 51] == pytest.approx(20.0)               # 200 - 180


def test_rotation_below_threshold_is_not_wrapped(gdi):
    curves = _mean_curves("r", value=0.0)
    curves["pelvis_rotation"] = [179.0] * 101

    vector = gdi.build_gdi_feature_vector(curves, "r", gdi.GDI9)

    assert vector[2 * 51] == pytest.approx(179.0)


def test_a_set_without_pelvis_needs_no_pelvis_adjustments(gdi):
    """The corrections are keyed by variable name, so a reduced set drops them
    with the variables. Previously they were an `if name ==` chain that would
    have gone looking for pelvis columns a 6-variable set does not have."""
    curves = _mean_curves("r", value=7.0, feature_set=gdi.REDUCED6)

    vector = gdi.build_gdi_feature_vector(curves, "r", gdi.REDUCED6)

    assert np.all(vector == 7.0)  # nothing offset by 20, nothing wrapped


def test_both_sides_use_their_own_joint_names(gdi):
    assert "knee_angle_r" in gdi.gdi_features("r", gdi.GDI9)
    assert "knee_angle_l" in gdi.gdi_features("l", gdi.GDI9)
    # pelvis terms are shared, not sided
    assert gdi.gdi_features("r", gdi.GDI9)[:3] == gdi.gdi_features("l", gdi.GDI9)[:3]


def test_missing_gdi_coordinate_names_the_gap_and_the_set(gdi):
    curves = _mean_curves("r")
    del curves["fpa_r"]

    with pytest.raises(KeyError, match="fpa_r"):
        gdi.build_gdi_feature_vector(curves, "r", gdi.GDI9)


def test_short_curve_is_rejected_rather_than_silently_sampled(gdi):
    curves = _mean_curves("r")
    curves["knee_angle_r"] = [1.0] * 40

    with pytest.raises(ValueError, match="101-point"):
        gdi.build_gdi_feature_vector(curves, "r", gdi.GDI9)


# -- reference loading -----------------------------------------------------


def test_missing_reference_names_the_files_and_the_feature_set(gdi, tmp_path):
    with pytest.raises(gdi.GdiReferenceMissingError) as caught:
        gdi.load_gdi_reference(tmp_path, gdi.REDUCED6)

    message = str(caught.value)
    assert "matrix_ms_reduced_old.csv" in message
    assert "controlCalc_ms_reduced_old.csv" in message
    assert "reduced6" in message


def test_half_populated_reference_directory_still_raises(gdi, tmp_path):
    """The exact shape of the original bug: one file present, one absent."""
    _write_reference(tmp_path, gdi.REDUCED5)
    (tmp_path / gdi.REDUCED5.control_filename).unlink()

    with pytest.raises(gdi.GdiReferenceMissingError,
                       match=gdi.REDUCED5.control_filename):
        gdi.load_gdi_reference(tmp_path, gdi.REDUCED5)


def test_reference_dimension_disagreement_is_caught_at_load(gdi, tmp_path):
    _write_reference(tmp_path, gdi.REDUCED5, n_components=15,
                     control=np.zeros(9))

    with pytest.raises(ValueError, match="same control dataset"):
        gdi.load_gdi_reference(tmp_path, gdi.REDUCED5)


def test_a_matrix_built_for_another_feature_set_is_caught_at_load(gdi, tmp_path):
    """The defect that made GDI unusable: a 5-variable matrix paired with a
    hardcoded 9-variable vector. It surfaced only at compute time, as a shape
    error naming no file. Now it fails at load, naming both counts."""
    # Write a 255-value (5-variable) matrix under REDUCED6's filenames.
    _write_reference(tmp_path, gdi.REDUCED6, vector_length=255)

    with pytest.raises(ValueError) as caught:
        gdi.load_gdi_reference(tmp_path, gdi.REDUCED6)

    message = str(caught.value)
    assert "255" in message and "306" in message
    assert "matrix_ms_reduced_old.csv" in message


def test_reference_loads_transposed_and_remembers_its_feature_set(gdi, tmp_path):
    _write_reference(tmp_path, gdi.REDUCED6, n_components=27)

    reference = gdi.load_gdi_reference(tmp_path, gdi.REDUCED6)

    assert reference["matrix"].shape == (27, 306)
    assert reference["control_mean"].shape == (27,)
    # Carried on the reference so compute_gdi cannot be handed a different set.
    assert reference["feature_set"] is gdi.REDUCED6


# -- the score itself ------------------------------------------------------


def test_subject_matching_the_control_mean_scores_exactly_100(gdi, tmp_path,
                                                              scoring_set):
    """GDI's definition: 100 is the control mean. Also guards log(0)."""
    _write_reference(tmp_path, scoring_set, n_components=15)
    vector = gdi.build_gdi_feature_vector(_mean_curves("r"), "r", scoring_set)
    reference = gdi.load_gdi_reference(tmp_path, scoring_set)
    reference["control_mean"] = reference["matrix"] @ vector

    assert gdi.compute_gdi(vector, reference) == pytest.approx(100.0)


def test_score_follows_the_published_formula(gdi, tmp_path, scoring_set):
    """Pins GDI = 100 - 10 * (ln(distance) - mean) / sd against an
    independently computed expectation."""
    _write_reference(tmp_path, scoring_set, n_components=15)
    reference = gdi.load_gdi_reference(tmp_path, scoring_set)
    vector = gdi.build_gdi_feature_vector(_mean_curves("r", value=2.0), "r",
                                          scoring_set)

    subject = reference["matrix"] @ vector
    diff = subject - reference["control_mean"]
    expected_z = (math.log(math.sqrt(float(np.sum(np.square(diff)))))
                  - scoring_set.ln_control_mean) / scoring_set.ln_control_sd

    assert gdi.compute_gdi(vector, reference) == pytest.approx(
        100.0 - 10.0 * expected_z)


def test_the_constants_come_from_the_feature_set_not_the_module(gdi):
    """They are properties of one control group projected through one matrix,
    not of GDI. The previous version kept them module-global, which is what
    made a wrong pairing possible."""
    means = {name: fs.ln_control_mean for name, fs in gdi.FEATURE_SETS.items()}

    assert len(set(means.values())) == len(means)  # all four differ
    assert not hasattr(gdi, "LN_CONTROL_MEAN")


@pytest.mark.parametrize("name,ln_mean,ln_sd", [
    ("gdi9", 4.716953, 0.292494),
    ("reduced6", 4.642758, 0.300381),
    ("reduced5", 4.448830, 0.281448),
    ("reduced4", 4.264782, 0.316835),
])
def test_the_promoted_control_constants_are_pinned(gdi, name, ln_mean, ln_sd):
    """Regenerated 2026-08-27 by gdi_reference.py from the 166-cycle pooled
    healthy-control cohort at 15 components, each validated held-out (control
    means 100.0-100.3, SDs 10.1-10.3). Pinned because a silent change here
    shifts every score the project produces."""
    feature_set = gdi.FEATURE_SETS[name]

    assert feature_set.ln_control_mean == pytest.approx(ln_mean)
    assert feature_set.ln_control_sd == pytest.approx(ln_sd)


def test_every_shipped_set_scores_against_healthy_controls(gdi):
    """GDI is defined as distance from a non-disabled control group. The
    cohort-derived constants that previously shipped (msflag 3.64317, sciflag
    4.518094) are superseded for that reason -- under them an average member
    of the impaired cohort scores ~100, which is not GDI."""
    for feature_set in gdi.FEATURE_SETS.values():
        assert feature_set.can_score
        assert "healthy-control cohort" in feature_set.provenance
    assert gdi.REDUCED5.ln_control_mean != pytest.approx(3.64317)
    assert gdi.REDUCED4.ln_control_mean != pytest.approx(4.518094)


def test_a_set_without_constants_refuses_to_score(gdi, tmp_path):
    """The old module promoted a commented-out constant to a live default and
    would have scored anything. An unattributable calibration must refuse, not
    produce a plausible wrong number. Every shipped set now has regenerated
    constants, so this uses a set built without them -- which is the state any
    new feature set starts in."""
    uncalibrated = gdi.GdiFeatureSet(
        name="uncalibrated",
        features=gdi.REDUCED6.features,
        matrix_filename=gdi.REDUCED6.matrix_filename,
        control_filename=gdi.REDUCED6.control_filename,
    )
    _write_reference(tmp_path, uncalibrated, n_components=27)
    reference = gdi.load_gdi_reference(tmp_path, uncalibrated)

    assert uncalibrated.can_score is False
    with pytest.raises(gdi.GdiConstantsMissingError, match="normative constants"):
        gdi.compute_gdi(np.ones(uncalibrated.vector_length), reference)


def test_the_old_unattributable_constant_is_not_calibrating_anything(gdi):
    """4.443685139 / 0.223457646 appears in the original only inside a
    commented-out line, and in no live path anywhere -- yet the previous
    version carried it as the module-wide default. No feature set may use it,
    and it must not be reachable as a module-level constant."""
    for feature_set in gdi.FEATURE_SETS.values():
        assert feature_set.ln_control_mean != pytest.approx(4.443685139)
        assert feature_set.ln_control_sd != pytest.approx(0.223457646)

    assert not hasattr(gdi, "LN_CONTROL_MEAN")
    assert not hasattr(gdi, "LN_CONTROL_SD")


def test_ten_points_is_one_standard_deviation(gdi):
    """The clinical interpretation the score exists to support."""
    assert gdi.REDUCED5.ln_control_sd > 0
    assert 100.0 - 10.0 * 1.0 == 90.0


def test_wrong_length_vector_is_rejected_with_both_numbers(gdi, tmp_path,
                                                           scoring_set):
    _write_reference(tmp_path, scoring_set, n_components=15)
    reference = gdi.load_gdi_reference(tmp_path, scoring_set)

    with pytest.raises(ValueError, match="459"):
        gdi.compute_gdi(np.ones(100), reference)


def test_gdi_for_trial_scores_both_sides_and_averages(gdi, tmp_path, scoring_set):
    _write_reference(tmp_path, scoring_set, n_components=15)
    reference = gdi.load_gdi_reference(tmp_path, scoring_set)
    results = {
        "curves_r": {"mean": _mean_curves("r", value=2.0)},
        "curves_l": {"mean": _mean_curves("l", value=3.0)},
    }

    scores = gdi.gdi_for_trial(results, reference)

    assert set(scores) == {"r", "l", "average"}
    assert scores["average"] == pytest.approx((scores["r"] + scores["l"]) / 2)


def test_gdi_features_exclude_translations_and_com(gdi):
    """Why GDI is usable on this project's IMU data at all: no variable in any
    feature set is a translation or centre-of-mass term, so the pinned-root
    limitation that invalidates gait_speed/stride_length does not touch it."""
    for feature_set in gdi.FEATURE_SETS.values():
        for side in ("r", "l"):
            for name in feature_set.feature_names(side):
                assert not name.startswith("com")
                assert "_t" not in name.replace("pelvis_tilt", "")
