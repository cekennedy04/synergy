"""Tests for curve_features.py -- exported curve matrices to GDI vectors.

The two layouts differ in both coordinate list and sampling, so most of what
matters here is that a value ends up in the row the reference expects. The
fixtures encode a known value per coordinate so a misplaced block is visible
rather than merely plausible.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cf():
    return _load("curve_features_under_test", "curve_features.py")


@pytest.fixture(scope="module")
def gdi():
    return _load("gdi_for_curve_tests", "gdi.py")


@pytest.fixture(scope="module")
def row_order(cf):
    return cf.exported_row_order()


def _matrix(row_order, n_strides=3, value_for=None):
    """An export where every point of coordinate i holds a known value."""
    value_for = value_for or (lambda index, name: float(index))
    blocks = [np.full((101, n_strides), value_for(i, n))
              for i, n in enumerate(row_order)]
    return np.vstack(blocks)


# -- the row ordering comes from the exporter ------------------------------


def test_the_row_order_is_read_from_the_driver_not_duplicated(cf, row_order):
    """The exported CSVs are headerless -- row position is the only thing
    identifying a coordinate. Hardcoding the list in a second place lets the
    two drift, and every score then shifts by a coordinate."""
    assert len(row_order) == 38
    assert row_order[0] == "pelvis_tilt"
    assert row_order[-2:] == ["fpa_r", "fpa_l"]


def test_the_export_carries_what_ucm_needs_and_gdi_does_not(cf, row_order):
    """Why the export is not reduced to six: COM and lumbar are UCM inputs
    that no GDI feature set uses. Shrinking it would delete them."""
    for name in ("comx", "comy", "comz",
                 "lumbar_extension", "lumbar_bending", "lumbar_rotation"):
        assert name in row_order


# -- loading ---------------------------------------------------------------


def test_a_matrix_of_the_wrong_height_is_rejected(cf, tmp_path, row_order):
    path = tmp_path / "wrong.csv"
    np.savetxt(path, np.ones((3000, 4)), delimiter=",")

    with pytest.raises(ValueError, match="3838"):
        cf.load_curve_matrix(path, row_order)


def test_non_finite_values_are_rejected(cf, tmp_path, row_order):
    data = _matrix(row_order, n_strides=2)
    data[0, 0] = np.nan
    path = tmp_path / "nan.csv"
    np.savetxt(path, data, delimiter=",")

    with pytest.raises(ValueError, match="non-finite"):
        cf.load_curve_matrix(path, row_order)


def test_a_single_stride_file_is_not_read_as_one_long_row(cf, tmp_path,
                                                          row_order):
    """genfromtxt collapses a one-column file to 1-D; read back as a row it
    would be 1x3838 and every block index would be wrong."""
    path = tmp_path / "one.csv"
    np.savetxt(path, _matrix(row_order, n_strides=1), delimiter=",")

    matrix = cf.load_curve_matrix(path, row_order)

    assert matrix.shape == (3838, 1)


# -- building the feature vector -------------------------------------------


def test_each_variable_lands_in_its_own_block(cf, gdi, row_order):
    """The check that catches an off-by-one coordinate: each variable's 51
    rows must all carry that coordinate's own marker value."""
    matrix = _matrix(row_order)

    vectors = cf.to_feature_vectors(matrix, "right", gdi.REDUCED6, gdi,
                                    row_order)

    for position, template in enumerate(gdi.REDUCED6.features):
        name = template.format(side="r")
        block = vectors[position * 51:(position + 1) * 51, 0]
        assert np.all(block == float(row_order.index(name)))


def test_the_vector_length_matches_the_feature_set(cf, gdi, row_order):
    matrix = _matrix(row_order, n_strides=4)

    for feature_set in (gdi.REDUCED6, gdi.GDI9, gdi.REDUCED4):
        vectors = cf.to_feature_vectors(matrix, "right", feature_set, gdi,
                                        row_order)
        assert vectors.shape == (feature_set.vector_length, 4)


def test_the_cycle_is_resampled_from_101_points_to_51(cf, gdi, row_order):
    """The two layouts disagree on sampling as well as coordinates: the export
    is 101 points per coordinate, GDI takes every other one."""
    ramp = np.tile(np.arange(101, dtype=float)[:, None], (1, 2))
    matrix = _matrix(row_order, n_strides=2)
    start = row_order.index("knee_angle_r") * 101
    matrix[start:start + 101, :] = ramp

    vectors = cf.to_feature_vectors(matrix, "right", gdi.REDUCED6, gdi,
                                    row_order)
    position = list(gdi.REDUCED6.features).index("knee_angle_{side}")
    block = vectors[position * 51:(position + 1) * 51, 0]

    assert block[:3].tolist() == [0.0, 2.0, 4.0]
    assert block[-1] == 100.0


def test_the_side_selects_that_leg_s_coordinates(cf, gdi, row_order):
    matrix = _matrix(row_order)

    right = cf.to_feature_vectors(matrix, "right", gdi.REDUCED6, gdi, row_order)
    left = cf.to_feature_vectors(matrix, "left", gdi.REDUCED6, gdi, row_order)

    assert not np.array_equal(right, left)
    assert right[0, 0] == float(row_order.index("hip_flexion_r"))
    assert left[0, 0] == float(row_order.index("hip_flexion_l"))


def test_an_unknown_side_is_rejected(cf, gdi, row_order):
    with pytest.raises(ValueError, match="side must be"):
        cf.to_feature_vectors(_matrix(row_order), "middle", gdi.REDUCED6, gdi,
                              row_order)


# -- the per-variable adjustments --------------------------------------------


def test_the_pelvis_offset_applies_only_where_pelvis_is_in_the_set(cf, gdi,
                                                                   row_order):
    """gdi9 carries pelvis_tilt and must be offset by +20; reduced6 has no
    pelvis at all, so nothing may be adjusted."""
    matrix = _matrix(row_order, value_for=lambda i, n: 5.0)

    nine = cf.to_feature_vectors(matrix, "right", gdi.GDI9, gdi, row_order)
    six = cf.to_feature_vectors(matrix, "right", gdi.REDUCED6, gdi, row_order)

    assert nine[0, 0] == pytest.approx(25.0)   # pelvis_tilt + 20
    assert np.all(six == 5.0)                  # untouched


def test_a_coordinate_absent_from_the_export_names_itself(cf, gdi, row_order):
    trimmed = [n for n in row_order if n != "fpa_r"]
    matrix = _matrix(trimmed)

    with pytest.raises(KeyError, match="fpa_r"):
        cf.to_feature_vectors(matrix, "right", gdi.REDUCED6, gdi, trimmed)


# -- scoring ---------------------------------------------------------------


def test_scores_come_back_one_per_stride(cf, gdi, row_order, tmp_path):
    matrix = _matrix(row_order, n_strides=7)
    rng = np.random.default_rng(0)
    length = gdi.REDUCED6.vector_length
    basis = np.linalg.qr(rng.normal(size=(length, 12)))[0].T
    reference = {"matrix": basis, "control_mean": np.zeros(12),
                 "feature_set": gdi.REDUCED6}

    scores = cf.score_curves(matrix, "right", reference, gdi.REDUCED6, gdi,
                             row_order)

    assert scores.shape == (7,)
    assert np.all(np.isfinite(scores))


def test_the_cli_reports_a_bad_reference_instead_of_a_traceback(cf, gdi,
                                                                tmp_path, capsys):
    """An unusable reference is an operator-actionable condition, and every one
    of these errors is already a full sentence saying what to do. A stack trace
    buries that -- the same complaint edit #14 in VENDORING.md records against
    numpy's 'negative dimensions are not allowed'."""
    curves = tmp_path / "curves.csv"
    row_order = cf.exported_row_order()
    np.savetxt(curves, _matrix(row_order), delimiter=",")
    # A reference directory with the right filenames and a non-basis matrix.
    reference = tmp_path / "ref"
    reference.mkdir()
    length = gdi.REDUCED6.vector_length
    np.savetxt(reference / gdi.REDUCED6.matrix_filename,
               np.ones((length, 4)), delimiter=",")
    np.savetxt(reference / gdi.REDUCED6.control_filename,
               np.zeros((1, 4)), delimiter=",")

    code = cf.main(["--curves", str(curves), "--side", "right",
                    "--reference", str(reference), "--feature-set", "reduced6"])

    assert code == 1
    out = capsys.readouterr().out
    assert "Cannot load the GDI reference." in out
    assert "orthonormal" in out
