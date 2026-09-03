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
    # A real orthonormal basis, as load_gdi_reference now requires: GDI's
    # distance is only meaningful through an orthonormal projection, and an
    # arange-filled matrix is not one.
    rng = np.random.default_rng(0)
    matrix = np.linalg.qr(rng.normal(size=(length, n_components)))[0].T
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


def test_pelvis_tilt_is_no_longer_offset_and_the_rotation_wrap_remains(gdi):
    """The `+20` on pelvis_tilt was removed 2026-09-02: it was a legacy
    correction for an input pipeline whose raw tilt sat near 0, and applied to
    this pipeline's 21.23 deg it produced 41.23 -- non-physiological against
    published norms of 12 +/- 4, so wrong whichever frame turns out to be
    authoritative.

    Pinned in the negative so it cannot return as a "fix", and so that anyone
    reinstating an offset has to justify the number. The rotation wrap stays:
    it is a range fix (bring a near-360 value back inside +/-180), not a frame
    correction, and it stands on its own."""
    curves = _mean_curves("r", value=0.0)
    curves["pelvis_tilt"] = [5.0] * 101
    curves["pelvis_rotation"] = [200.0] * 101

    vector = gdi.build_gdi_feature_vector(curves, "r", gdi.GDI9)

    assert vector[0] == pytest.approx(5.0), (
        "pelvis_tilt must pass through unmodified. A fitted offset is not the "
        "replacement -- see the _CURVE_ADJUSTMENTS note in gdi.py."
    )
    assert "pelvis_tilt" not in gdi._CURVE_ADJUSTMENTS
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

    # check_digest=False: this is a synthetic basis written under a shipped
    # feature set's filenames, which is exactly the pairing the digest check
    # exists to refuse. The shape/transposition contract under test is
    # independent of it.
    reference = gdi.load_gdi_reference(tmp_path, gdi.REDUCED6,
                                       check_digest=False)

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


def test_every_shipped_set_can_score(gdi):
    """GDI is defined as distance from a non-disabled control group, so the
    superseded archived constants must not be what ships."""
    for feature_set in gdi.FEATURE_SETS.values():
        assert feature_set.can_score
    assert gdi.REDUCED5.ln_control_mean != pytest.approx(3.64317)
    assert gdi.REDUCED4.ln_control_mean != pytest.approx(4.518094)


def test_a_rescaled_basis_is_refused_at_load(gdi, tmp_path, scoring_set):
    """The defect shape checks cannot see. Two archived matrices have column
    norms from 0.03 to 1.0; projections onto the shrunken columns collapse the
    distance, so healthy controls read 118 through one of them while every
    shape check passes. GDI's distance is only meaningful through an
    orthonormal projection."""
    matrix = _write_reference(tmp_path, scoring_set, n_components=15)
    # Same basis, columns rescaled -- exactly the archived failure mode.
    rescaled = matrix.copy()
    rescaled[3:, :] *= 0.05
    with open(tmp_path / scoring_set.matrix_filename, "w", newline="") as handle:
        csv.writer(handle).writerows(rescaled.T)

    with pytest.raises(ValueError, match="orthonormal"):
        gdi.load_gdi_reference(tmp_path, scoring_set)


def test_reproducing_a_historic_result_can_opt_out_of_the_check(gdi, tmp_path,
                                                                scoring_set):
    """The archived matrices still need to be loadable on purpose."""
    matrix = _write_reference(tmp_path, scoring_set, n_components=15)
    rescaled = matrix.copy()
    rescaled[3:, :] *= 0.05
    with open(tmp_path / scoring_set.matrix_filename, "w", newline="") as handle:
        csv.writer(handle).writerows(rescaled.T)

    reference = gdi.load_gdi_reference(tmp_path, scoring_set,
                                       check_orthonormality=False)

    assert reference["matrix"].shape[0] == 15


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


def test_ten_points_is_one_standard_deviation(gdi, tmp_path, scoring_set):
    """The clinical interpretation the score exists to support, exercised
    through compute_gdi rather than asserted as arithmetic on literals: a
    subject one log-SD further from the control mean scores 10 points lower."""
    _write_reference(tmp_path, scoring_set, n_components=15)
    reference = gdi.load_gdi_reference(tmp_path, scoring_set)
    vector = gdi.build_gdi_feature_vector(_mean_curves("r", value=2.0), "r",
                                          scoring_set)
    baseline = gdi.compute_gdi(vector, reference)

    # Push the subject exactly one ln-SD further away.
    subject = reference["matrix"] @ vector
    offset = subject - reference["control_mean"]
    farther = dict(reference)
    farther["control_mean"] = subject - offset * math.exp(scoring_set.ln_control_sd)

    assert gdi.compute_gdi(vector, farther) == pytest.approx(baseline - 10.0)


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
        "curves_r": {"mean": _mean_curves("r", value=2.0),
                     "indiv": [_mean_curves("r", value=2.0)]},
        "curves_l": {"mean": _mean_curves("l", value=3.0),
                     "indiv": [_mean_curves("l", value=3.0)]},
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


# -- the scoring unit ------------------------------------------------------
# Regression cover for docs/2026-08-31-gdi-vs-ucm-audit.md section 3:
# gdi_for_trial used to score curves['mean'] against constants calibrated on
# individual gait cycles, which reads high on every trial.


def test_gdi_for_side_scores_cycles_not_the_mean_curve(gdi, tmp_path,
                                                       scoring_set):
    """The whole point of the fix: with cycles that differ from each other,
    the mean of the per-cycle scores is NOT the score of the mean curve, and
    the calibrated answer is the former."""
    _write_reference(tmp_path, scoring_set, n_components=15)
    reference = gdi.load_gdi_reference(tmp_path, scoring_set)

    cycles = [_mean_curves("r", value=v) for v in (1.0, 3.0, 5.0)]
    mean_curve = _mean_curves("r", value=3.0)  # the average of those three
    curves = {"mean": mean_curve, "indiv": cycles}

    scored = gdi.gdi_for_side(curves, "r", reference)
    per_cycle = [
        gdi.compute_gdi(gdi.build_gdi_feature_vector(c, "r", scoring_set),
                        reference, scoring_set)
        for c in cycles
    ]
    on_the_mean = gdi.compute_gdi(
        gdi.build_gdi_feature_vector(mean_curve, "r", scoring_set),
        reference, scoring_set)

    assert scored == pytest.approx(sum(per_cycle) / 3)
    # The two conventions genuinely disagree here -- if they did not, this
    # test would be asserting nothing.
    assert scored != pytest.approx(on_the_mean)


def test_a_cycle_calibrated_set_refuses_to_score_a_bare_mean_curve(
        gdi, tmp_path, scoring_set):
    """Refusing beats falling back. A fallback to curves['mean'] returns a
    number that is always too high and indistinguishable downstream."""
    _write_reference(tmp_path, scoring_set, n_components=15)
    reference = gdi.load_gdi_reference(tmp_path, scoring_set)

    with pytest.raises(KeyError, match="per gait cycle"):
        gdi.gdi_for_side({"mean": _mean_curves("r")}, "r", reference)


def test_every_shipped_feature_set_declares_a_scoring_unit(gdi):
    """The constants were all derived from per-cycle log distances over the
    166-column pooled cohort, so every shipped set must say so."""
    for feature_set in gdi.FEATURE_SETS.values():
        assert feature_set.scoring_unit == gdi.SCORING_UNIT_CYCLE


def test_a_mean_curve_set_still_scores_the_mean_curve(gdi, tmp_path, scoring_set):
    """The unit is a property of the calibration, not a hardcoded rule: a set
    calibrated on mean curves must score them."""
    import dataclasses
    feature_set = dataclasses.replace(
        scoring_set, scoring_unit=gdi.SCORING_UNIT_MEAN_CURVE)
    _write_reference(tmp_path, feature_set, n_components=15)
    reference = gdi.load_gdi_reference(tmp_path, feature_set)

    curves = {"mean": _mean_curves("r", value=2.0)}  # no 'indiv' at all
    scored = gdi.gdi_for_side(curves, "r", reference, feature_set)

    expected = gdi.compute_gdi(
        gdi.build_gdi_feature_vector(curves["mean"], "r", feature_set),
        reference, feature_set)
    assert scored == pytest.approx(expected)


# -- reference provenance --------------------------------------------------


def test_a_basis_from_another_cohort_is_refused(gdi, tmp_path):
    """The gap the orthonormality check cannot see. A well-formed basis from
    the wrong cohort passes every shape and orthonormality test and shifts
    every score -- the archived gdi9 basis scores healthy controls at 100.8."""
    _write_reference(tmp_path, gdi.GDI9, n_components=15)

    with pytest.raises(gdi.GdiReferenceMismatchError, match="digest"):
        gdi.load_gdi_reference(tmp_path, gdi.GDI9)


def test_the_digest_check_can_be_waived_for_historic_results(gdi, tmp_path):
    _write_reference(tmp_path, gdi.GDI9, n_components=15)

    reference = gdi.load_gdi_reference(tmp_path, gdi.GDI9, check_digest=False)

    assert reference["digest_verified"] is False
    assert reference["matrix"].shape == (15, 459)


def test_a_set_without_an_expected_digest_reports_itself_unverified(
        gdi, tmp_path, scoring_set):
    """`scoring_set` is a synthetic set carrying no expected digest, so the
    check cannot run -- and the reference must say so rather than imply it
    passed."""
    _write_reference(tmp_path, scoring_set, n_components=15)

    reference = gdi.load_gdi_reference(tmp_path, scoring_set)

    assert scoring_set.reference_digest is None
    assert reference["digest_verified"] is False
    assert len(reference["digest"]) == 64


def test_gdi_for_side_accepts_the_real_runtime_type(gdi, tmp_path, scoring_set):
    """`get_coordinates_normalized_time` returns pandas DataFrames, not dicts
    of lists. The feature builder indexes curves positionally (`curve[point]`),
    which on a DataFrame column is *label* lookup -- correct only because the
    frames carry a default RangeIndex. Pinned because everything else in this
    file tests dicts, and the two types take different code paths in pandas."""
    pd = pytest.importorskip("pandas")
    _write_reference(tmp_path, scoring_set, n_components=15)
    reference = gdi.load_gdi_reference(tmp_path, scoring_set)

    names = list(scoring_set.feature_names("r"))
    frames = [pd.DataFrame({name: [value] * 101 for name in names})
              for value in (1.0, 3.0, 5.0)]
    curves = {"mean": frames[1], "indiv": frames}

    scored = gdi.gdi_for_side(curves, "r", reference)
    expected = [
        gdi.compute_gdi(gdi.build_gdi_feature_vector(frame, "r", scoring_set),
                        reference, scoring_set)
        for frame in frames
    ]

    assert scored == pytest.approx(sum(expected) / 3)


def test_gdi9_is_refused_by_name_because_the_frame_mismatch_is_unresolved(gdi):
    """`--feature-set gdi9` is a documented CLI flag, so the name path is how a
    user actually reaches the defect. Before it was disabled this ran clean and
    returned 82.6 where reduced6 returned 88.4.

    Named for the frame mismatch, not the pelvis convention. Section 11 of the
    audit disabled gdi9 for a `pelvis_tilt` convention mismatch; section 12
    found the mismatch is general -- `hip_flexion` is off by -13.47 deg
    against the cohort, larger than any pelvis term -- and recorded the
    pelvis-only framing as too narrow."""
    with pytest.raises(gdi.GdiFeatureSetDisabledError) as excinfo:
        gdi.get_feature_set("gdi9")

    message = str(excinfo.value)
    assert "frame" in message and "reduced6" in message, (
        "the refusal must say what is wrong and what to use instead; an "
        "operator who only sees 'disabled' has nowhere to go."
    )
    assert "hip_flexion" in message, (
        "the reason must name a variable outside the pelvis. That is the whole "
        "difference between what section 11 recorded and what section 12 "
        "found: a pelvis-only reason implies reduced6 is clean, and reduced6 "
        "carries the largest offset in the set (hip_flexion, -13.47 deg) while "
        "every number this project reports comes through it. Checking for the "
        "word 'frame' alone does not catch a narrowing -- it survives in the "
        "closing sentences even when the lead is rewritten back to pelvis. "
        "Verified by mutation."
    )


def test_gdi9_is_refused_when_passed_as_an_object_not_just_by_name(gdi, tmp_path):
    """get_feature_set duck-types feature-set objects straight through, so the
    name guard alone leaves `compute_gdi(vector, ref, gdi.GDI9)` open. Scoring
    is the last point where refusing still stops a wrong number existing."""
    reference = {"matrix": np.eye(gdi.REDUCED6.vector_length),
                 "control_mean": np.zeros(gdi.REDUCED6.vector_length)}

    with pytest.raises(gdi.GdiFeatureSetDisabledError):
        gdi.compute_gdi(np.ones(gdi.GDI9.vector_length), reference, gdi.GDI9)


def test_the_disabled_set_is_defined_but_not_scoreable(gdi):
    """Disabled means out of service, not deleted: the recovered feature order,
    the regenerated constants and the digest are all still needed to read the
    audit and to rebuild gdi9 once the frame question is resolved."""
    assert gdi.GDI9.is_disabled
    assert gdi.GDI9.can_score, (
        "gdi9 still has attributed constants -- it is disabled for a "
        "convention mismatch, not for missing calibration. Conflating the two "
        "would lose the distinction GdiConstantsMissingError exists to draw."
    )
    assert gdi.FEATURE_SETS["gdi9"] is gdi.GDI9

    # An enabled set must not silently acquire a curve adjustment. This is a
    # narrower claim than it used to make, and the difference matters.
    #
    # It once read "the sets that remain in service stay clear of the
    # adjustments that caused the mismatch; that is precisely why they are
    # unaffected." Both halves stopped being true on 2026-09-02:
    #
    #   - _CURVE_ADJUSTMENTS no longer holds a frame correction. The +20 on
    #     pelvis_tilt is gone; what remains is the pelvis_rotation 180 wrap,
    #     which is a range fix that stands on its own and causes no mismatch.
    #   - reduced6 is NOT unaffected. Section 12 of the audit measures it at
    #     80.20 +/- 8.09 against the cohort's 100.0 +/- 10.0 -- a 19.8-point
    #     deficit with zero pelvis involvement, carrying the largest offset in
    #     the set (hip_flexion, -13.47 deg). reduced6 is a smaller exposure to
    #     the frame mismatch, not immunity from it, and every number this
    #     project reports comes through it.
    #
    # So this loop pins bookkeeping -- an adjustment applies only where the
    # set declares the variable -- and nothing about validity.
    adjusted = set(gdi._CURVE_ADJUSTMENTS)
    for name, feature_set in gdi.FEATURE_SETS.items():
        if feature_set.is_disabled:
            continue
        assert not (set(feature_set.features) & adjusted), (
            f"{name} is enabled and gained a variable that _CURVE_ADJUSTMENTS "
            "touches. Check what the adjustment is before assuming this is "
            "fine: a range fix is harmless, a frame correction is the thing "
            "gdi9 is disabled for."
        )
    assert not gdi.DEFAULT_FEATURE_SET.is_disabled
