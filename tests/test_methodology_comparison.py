"""Tests for methodology_comparison.py.

The exported curve CSVs carry no labels -- row position is the only thing
identifying a coordinate -- so the row-mapping guard is the most important
thing here. A silent desynchronisation between JOINT_NAMES and this reader
would mislabel every number in the report while looking entirely plausible.

Equally important: neither GDI nor the synergy index can be computed today,
and both must say so rather than returning a placeholder. A zero or a NaN in
a results table is indistinguishable from a real measurement.
"""
import csv
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "methodology_comparison.py"
POINTS = 101


@pytest.fixture(scope="module")
def mc():
    spec = importlib.util.spec_from_file_location("methodology_comparison_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_matrix(path, names, n_cycles=4, value_fn=None):
    """Write a curve matrix in the real export's layout: (len(names)*101) rows
    by n_cycles columns, no labels."""
    rows = []
    for i, name in enumerate(names):
        for point in range(POINTS):
            if value_fn is None:
                rows.append([float(i)] * n_cycles)
            else:
                rows.append([value_fn(name, point, c) for c in range(n_cycles)])
    np.savetxt(path, np.array(rows), delimiter=",", fmt="%f")


# -- row mapping, the thing that silently breaks -------------------------


def test_row_blocks_map_to_the_right_coordinates(mc, tmp_path):
    names = ["a", "b", "c"]
    path = tmp_path / "m.csv"
    _write_matrix(path, names)

    loaded = mc.load_curve_matrix(path, names)

    assert list(loaded) == names
    # block i was written as constant float(i)
    for i, name in enumerate(names):
        assert loaded[name].shape == (POINTS, 4)
        assert np.allclose(loaded[name], float(i))


def test_row_count_mismatch_is_rejected_not_silently_truncated(mc, tmp_path):
    """The failure mode this guard exists for: JOINT_NAMES gaining or losing a
    coordinate (fpa_r/fpa_l were added 2026-08-20) while a reader still assumes
    the old length. Every row block after the divergence would be mislabelled."""
    path = tmp_path / "m.csv"
    _write_matrix(path, ["a", "b", "c"])

    with pytest.raises(ValueError, match="row mapping would be silently wrong"):
        mc.load_curve_matrix(path, ["a", "b"])


def test_joint_names_comes_from_the_driver_not_a_local_copy(mc):
    """A duplicated list would drift. This must read the driver's own."""
    names = mc.joint_names()

    assert "pelvis_tilt" in names and "comz" in names
    assert names[0] == "pelvis_tilt"          # order is the row mapping
    assert len(names) == len(set(names))


# -- variability ---------------------------------------------------------


def test_single_stride_gives_nan_not_zero(mc):
    """Across-stride variance is undefined for one stride. Returning 0.0 would
    make a single-cycle trial look perfectly repeatable."""
    assert np.isnan(mc.across_stride_sd(np.ones((POINTS, 1))))


def test_identical_strides_give_zero_sd(mc):
    assert mc.across_stride_sd(np.ones((POINTS, 4))) == 0.0


def test_sd_is_mean_across_the_cycle(mc):
    block = np.zeros((POINTS, 2))
    block[:, 1] = 2.0            # SD of {0,2} is 1.0 at every point
    assert mc.across_stride_sd(block) == pytest.approx(1.0)


# -- classification ------------------------------------------------------


def _summaries(sd_by_method, name):
    return {
        method: {"coordinates": {name: {"sd": sd, "min": 0.0, "max": 1.0}}}
        for method, sd in sd_by_method.items()
    }


def test_pinned_root_is_flagged_for_the_imu_methodology(mc):
    status, reason = mc.classify("pelvis_tx", _summaries({"Xsens": 0.0, "OpenCap": 1.2}, "pelvis_tx"))

    assert status == "imu-degenerate"
    assert "pinned" in reason


def test_the_upper_limb_is_no_longer_excluded_by_name(mc):
    """Was `imu-invalid` from 2026-08-25 until the calibration-pose defect
    behind it was fixed on 2026-09-02. The arms now agree with Xsens's own
    <jointAngle> solver to within a few degrees, so a hardcoded exclusion
    would be discarding real data. Saturation is what should exclude a
    coordinate now, and it is measured per export -- see
    test_a_coordinate_pinned_against_its_bound_is_flagged."""
    status, _reason = mc.classify(
        "arm_rot_l", _summaries({"Xsens": 1.8, "OpenCap": 3.3}, "arm_rot_l"))

    assert status == "usable"
    assert mc.INVALID_IMU_ONLY == set()


def test_toe_joint_is_degenerate_in_both_methodologies(mc):
    status, _ = mc.classify("mtp_angle_r", _summaries({"Xsens": 0.0, "OpenCap": 0.0}, "mtp_angle_r"))

    assert status == "degenerate (both)"


def test_a_clean_coordinate_is_usable(mc):
    status, reason = mc.classify("knee_angle_r", _summaries({"Xsens": 1.2, "OpenCap": 2.3}, "knee_angle_r"))

    assert status == "usable"
    assert reason == ""


# -- blocked analyses must say so ----------------------------------------


def _orthonormal(n_components, vector_length):
    """A real basis with orthonormal rows. load_gdi_reference now requires
    one: GDI's distance is only meaningful through an orthonormal projection,
    and two archived matrices turned out to be rescaled rather than bases."""
    rng = np.random.default_rng(0)
    return np.linalg.qr(rng.normal(size=(vector_length, n_components)))[0].T


def test_gdi_reports_blocked_without_reference_data(mc):
    result = mc.gdi_comparison({}, reference_dir=None)

    assert result["available"] is False
    assert result["scores"] == {}
    assert "normative control group" in result["reason"]


def test_gdi_blocked_reason_names_the_required_files(mc):
    """The filenames come from the selected feature set, so the message stays
    correct when the set changes -- it used to hardcode one pair."""
    result = mc.gdi_comparison({}, reference_dir=None, feature_set="reduced5")

    assert "matrix_ms_reduced.csv" in result["reason"]
    assert "controlCalc_ms_reduced.csv" in result["reason"]
    assert "reduced5" in result["reason"]


def test_a_different_feature_set_names_its_own_files(mc):
    result = mc.gdi_comparison({}, reference_dir=None, feature_set="reduced6")

    assert "matrix_ms_reduced_old.csv" in result["reason"]
    assert "matrix_ms_reduced.csv" not in result["reason"]


def test_gdi_with_an_empty_reference_directory_still_reports_blocked(mc, tmp_path):
    result = mc.gdi_comparison({}, reference_dir=tmp_path, feature_set="reduced5")

    assert result["available"] is False
    assert "matrix_ms_reduced.csv" in result["reason"]


def test_a_set_without_normative_constants_reports_blocked_not_a_score(mc, tmp_path,
                                                                       monkeypatch):
    """A loadable reference is not enough: a set with no attributed ln
    constants must say so rather than score. Every shipped set now has
    regenerated constants, so this strips them from one."""
    n_components, vector_length = 27, 306
    matrix = _orthonormal(n_components, vector_length)
    with open(tmp_path / "matrix_ms_reduced_old.csv", "w", newline="") as handle:
        csv.writer(handle).writerows(matrix.T)
    with open(tmp_path / "controlCalc_ms_reduced_old.csv", "w", newline="") as handle:
        csv.writer(handle).writerow(np.zeros(n_components))

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_gdi_for_mc_test", Path(mc.__file__).parent / "gdi.py")
    gdi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gdi)
    uncalibrated = gdi.GdiFeatureSet(
        name="uncalibrated6", features=gdi.REDUCED6.features,
        matrix_filename=gdi.REDUCED6.matrix_filename,
        control_filename=gdi.REDUCED6.control_filename,
    )

    result = mc.gdi_comparison({}, reference_dir=tmp_path,
                               feature_set=uncalibrated)

    assert result["available"] is False
    assert result["scores"] == {}
    assert "normative constants" in result["reason"]


def test_gdi_computes_for_every_methodology_once_reference_exists(mc, tmp_path):
    """The slot fills automatically -- no code change needed when the
    collaborator supplies the control dataset."""
    # reduced5 is the set the supervisor's live script actually uses, and the
    # only shipped set with both a reference pair and attributed constants.
    n_components, vector_length = 28, 255
    matrix = _orthonormal(n_components, vector_length)
    with open(tmp_path / "matrix_ms_reduced.csv", "w", newline="") as handle:
        csv.writer(handle).writerows(matrix.T)
    with open(tmp_path / "controlCalc_ms_reduced.csv", "w", newline="") as handle:
        csv.writer(handle).writerow(np.zeros(n_components))

    def curves(side, value):
        names = [f"hip_flexion_{side}", f"hip_adduction_{side}",
                 f"knee_angle_{side}", f"ankle_angle_{side}", f"fpa_{side}"]
        one = {n: [value] * 101 for n in names}
        # reduced5 is calibrated per gait cycle, so a result that carries only
        # a mean curve cannot be scored against it -- see gdi.SCORING_UNIT_CYCLE.
        return {"mean": one, "indiv": [one]}

    results = {
        "Xsens": {"curves_r": curves("r", 2.0), "curves_l": curves("l", 2.0)},
        "OpenCap": {"curves_r": curves("r", 3.0), "curves_l": curves("l", 3.0)},
    }

    # check_digest=False: the matrix above is random, so it is deliberately
    # not the reference reduced5's shipped constants were derived through.
    result = mc.gdi_comparison(results, reference_dir=tmp_path,
                               feature_set="reduced5", check_digest=False)

    assert result["available"] is True
    assert set(result["scores"]) == {"Xsens", "OpenCap"}
    for scores in result["scores"].values():
        assert set(scores) == {"r", "l", "average"}


def test_synergy_status_never_returns_a_number(mc):
    """A placeholder 0 or NaN in a results table is indistinguishable from a
    computed value. It must report unavailability instead."""
    status = mc.synergy_status()

    assert status["available"] is False
    assert "value" not in status and "score" not in status
    assert "task variable" in status["reason"]


def test_synergy_reason_records_the_com_asymmetry_between_methodologies(mc):
    """The decisive constraint: a global-COM task variable is available to the
    video methodology but not the IMU one."""
    reason = mc.synergy_status()["reason"]

    assert "pinned" in reason
    assert "OpenCap" in reason and "relative to pelvis" in reason


# -- end-to-end over a small synthetic curve directory -------------------


def test_summarise_reports_stride_counts_and_ranges(mc, tmp_path):
    names = ["pelvis_tilt", "knee_angle_r"]
    for trial, cycles in (("001", 4), ("002", 6)):
        _write_matrix(tmp_path / f"CK-CK-{trial}_right.csv", names, n_cycles=cycles,
                      value_fn=lambda n, p, c: float(c))

    summary = mc.summarise_methodology(tmp_path, "CK-CK-", ["001", "002"], names)

    assert summary["n_trials"] == 2
    assert summary["n_strides"] == 10
    assert summary["coordinates"]["knee_angle_r"]["min"] == 0.0
    assert summary["coordinates"]["knee_angle_r"]["max"] == 5.0


def test_missing_curve_files_raise_rather_than_report_an_empty_comparison(mc, tmp_path):
    with pytest.raises(FileNotFoundError, match="Run the curve export first"):
        mc.summarise_methodology(tmp_path, "CK-CK-", ["001"], ["pelvis_tilt"])


def test_a_wrong_cohort_reference_is_reported_not_raised(mc, tmp_path):
    """Same contract as a missing reference: an unusable reference produces a
    stated reason, never an exception and never a fabricated score. A basis
    from another cohort loads cleanly and is a valid orthonormal basis, so
    only the digest catches it."""
    n_components, vector_length = 28, 255
    matrix = _orthonormal(n_components, vector_length)
    with open(tmp_path / "matrix_ms_reduced.csv", "w", newline="") as handle:
        csv.writer(handle).writerows(matrix.T)
    with open(tmp_path / "controlCalc_ms_reduced.csv", "w", newline="") as handle:
        csv.writer(handle).writerow(np.zeros(n_components))

    result = mc.gdi_comparison({}, reference_dir=tmp_path,
                               feature_set="reduced5")

    assert result["available"] is False
    assert result["scores"] == {}
    assert "digest" in result["reason"]


# -- bound saturation, the tripwire that was missing ----------------------
#
# Added 2026-09-02 with the calibration-pose fix. The arm defect it caught was
# visible for two weeks as "arm_flex_l reaches -566 deg" sitting in a prose
# note, because nothing in the code ever compared an exported curve against
# the model's own coordinate limits. A coordinate pinned against its bound is
# not a measurement -- it is the solver reporting that it ran out of room --
# and it looks entirely plausible in a table of degrees.


def _model_ranges_stub(**pairs):
    """{coordinate: (min_deg, max_deg)}, the shape read_model_coordinate_ranges
    returns."""
    return dict(pairs)


def test_a_coordinate_pinned_against_its_bound_is_flagged(mc, tmp_path):
    names = ["knee_angle_r", "arm_rot_l"]
    _write_matrix(
        tmp_path / "CK-CK-001_right.csv", names, n_cycles=2,
        value_fn=lambda name, point, cycle: 572.9 if name == "arm_rot_l" else 30.0,
    )
    summary = mc.summarise_methodology(tmp_path, "CK-CK-", ["001"], names)
    ranges = _model_ranges_stub(knee_angle_r=(-10.0, 150.0), arm_rot_l=(-572.96, 572.96))

    flagged = mc.saturated_coordinates(summary, ranges)

    assert "arm_rot_l" in flagged
    assert "knee_angle_r" not in flagged


def test_saturation_is_reported_with_the_bound_it_hit(mc, tmp_path):
    """A bare name is not actionable: which end, how close, and what the limit
    is are what tell you whether it is a calibration fault or a model whose
    range is genuinely narrower than the movement."""
    names = ["pro_sup_r"]
    _write_matrix(tmp_path / "CK-CK-001_right.csv", names, n_cycles=2,
                  value_fn=lambda name, point, cycle: 119.7)
    summary = mc.summarise_methodology(tmp_path, "CK-CK-", ["001"], names)

    flagged = mc.saturated_coordinates(summary, _model_ranges_stub(pro_sup_r=(0.0, 119.75)))

    entry = flagged["pro_sup_r"]
    assert entry["bound"] == "max"
    assert entry["limit"] == pytest.approx(119.75)
    assert entry["reached"] == pytest.approx(119.7)


def test_a_coordinate_well_inside_its_range_is_not_flagged(mc, tmp_path):
    names = ["arm_flex_r"]
    _write_matrix(tmp_path / "CK-CK-001_right.csv", names, n_cycles=2,
                  value_fn=lambda name, point, cycle: -3.0 + point * 0.1)
    summary = mc.summarise_methodology(tmp_path, "CK-CK-", ["001"], names)

    assert mc.saturated_coordinates(
        summary, _model_ranges_stub(arm_flex_r=(-572.96, 572.96))) == {}


def test_the_tolerance_is_configurable_and_defaults_to_one_degree(mc, tmp_path):
    """IK stops just shy of a bound rather than exactly on it, so an
    exact-equality test would never fire. One degree is tight enough not to
    flag real motion and loose enough to catch a pinned coordinate."""
    names = ["arm_rot_l"]
    _write_matrix(tmp_path / "CK-CK-001_right.csv", names, n_cycles=2,
                  value_fn=lambda name, point, cycle: 570.0)
    summary = mc.summarise_methodology(tmp_path, "CK-CK-", ["001"], names)
    ranges = _model_ranges_stub(arm_rot_l=(-572.96, 572.96))

    assert mc.saturated_coordinates(summary, ranges) == {}
    assert "arm_rot_l" in mc.saturated_coordinates(summary, ranges, tolerance_deg=5.0)


def test_a_coordinate_with_no_known_range_is_skipped_not_guessed(mc, tmp_path):
    """comx/comy/comz and the computed foot-progression angles are in the
    export but are not model coordinates at all."""
    names = ["comx"]
    _write_matrix(tmp_path / "CK-CK-001_right.csv", names, n_cycles=2,
                  value_fn=lambda name, point, cycle: 0.4)
    summary = mc.summarise_methodology(tmp_path, "CK-CK-", ["001"], names)

    assert mc.saturated_coordinates(summary, _model_ranges_stub()) == {}


_MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<OpenSimDocument Version="40000">
  <Model name="stub">
    <JointSet>
      <objects>
        <CustomJoint name="ground_pelvis">
          <SpatialTransform>
            <TransformAxis name="rotation1">
              <coordinates>pelvis_tilt</coordinates>
            </TransformAxis>
            <TransformAxis name="translation1">
              <coordinates>pelvis_tx</coordinates>
            </TransformAxis>
          </SpatialTransform>
          <coordinates>
            <Coordinate name="pelvis_tilt">
              <range>-1.5707963 1.5707963</range>
            </Coordinate>
            <Coordinate name="pelvis_tx">
              <range>-100 100</range>
            </Coordinate>
          </coordinates>
        </CustomJoint>
      </objects>
    </JointSet>
  </Model>
</OpenSimDocument>
"""


def test_coordinate_ranges_come_back_in_degrees(mc, tmp_path):
    """The .osim stores rotational ranges in radians; the curve exports are in
    degrees. Comparing the two without converting would never flag anything."""
    model = tmp_path / "stub.osim"
    model.write_text(_MODEL_XML)

    ranges = mc.read_model_coordinate_ranges(model)

    assert ranges["pelvis_tilt"] == pytest.approx((-90.0, 90.0), abs=1e-4)


def test_translational_coordinates_are_left_out_of_the_ranges(mc, tmp_path):
    """pelvis_tx's range is metres. Running degrees() over it produces a
    plausible-looking +/-5729 instead of an error, which is the same class of
    silent unit mistake this whole check exists to catch."""
    model = tmp_path / "stub.osim"
    model.write_text(_MODEL_XML)

    assert "pelvis_tx" not in mc.read_model_coordinate_ranges(model)


def test_the_report_names_any_coordinate_pinned_against_a_bound(mc, tmp_path):
    names = ["knee_angle_r", "arm_rot_l"]
    for prefix, trial in (("CK-CK-", "001"), ("OC-Trial", "1")):
        _write_matrix(
            tmp_path / f"{prefix}{trial}_right.csv", names, n_cycles=2,
            value_fn=lambda name, point, cycle: 572.9 if name == "arm_rot_l" else 30.0,
        )
    summaries = {
        "Xsens": mc.summarise_methodology(tmp_path, "CK-CK-", ["001"], names),
        "OpenCap": mc.summarise_methodology(tmp_path, "OC-Trial", ["1"], names),
    }
    ranges = {"knee_angle_r": (-10.0, 150.0), "arm_rot_l": (-572.96, 572.96)}

    report = mc.format_report(summaries, names, ranges)

    assert "arm_rot_l" in report
    assert "572.96" in report


def test_the_report_says_so_when_nothing_is_pinned(mc, tmp_path):
    """Silence would read the same as "not checked". After the 2026-09-02 fix
    the healthy answer is "none", and it has to be visible as one."""
    names = ["knee_angle_r"]
    _write_matrix(tmp_path / "CK-CK-001_right.csv", names, n_cycles=2,
                  value_fn=lambda name, point, cycle: 30.0)
    summaries = {"Xsens": mc.summarise_methodology(tmp_path, "CK-CK-", ["001"], names)}

    report = mc.format_report(summaries, names, {"knee_angle_r": (-10.0, 150.0)})

    assert "none" in report


def test_the_report_omits_the_bound_section_when_no_model_was_given(mc, tmp_path):
    names = ["knee_angle_r"]
    _write_matrix(tmp_path / "CK-CK-001_right.csv", names, n_cycles=2,
                  value_fn=lambda name, point, cycle: 30.0)
    summaries = {"Xsens": mc.summarise_methodology(tmp_path, "CK-CK-", ["001"], names)}

    assert "joint bound" not in mc.format_report(summaries, names)
