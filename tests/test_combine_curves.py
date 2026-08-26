"""Tests for combine_curves.py -- all of a participant's trials in one matrix.

The exported curve files carry no header: row position identifies the
coordinate and column position identifies the stride. Concatenating them is
therefore an operation with no self-describing output, so the things that can
go silently wrong -- column order, a trial with a different row count, a
mis-sorted trial sequence -- are what these tests pin.

A mis-ordered column is the dangerous failure: the file still loads, still has
the right shape, and every downstream number is wrong.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "combine_curves.py"
ROWS = 3838          # 38 coordinates x 101 points


@pytest.fixture(scope="module")
def cc():
    spec = importlib.util.spec_from_file_location("combine_curves_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path, n_strides, fill_base, rows=ROWS):
    """Each column is a distinct constant, so a column's origin is checkable."""
    matrix = np.zeros((rows, n_strides))
    for column in range(n_strides):
        matrix[:, column] = fill_base + column
    np.savetxt(path, matrix, delimiter=",", fmt="%f")


def test_combined_column_count_is_the_sum_of_strides(cc, tmp_path):
    _write(tmp_path / "S-T01_right.csv", 4, 100.0)
    _write(tmp_path / "S-T02_right.csv", 6, 200.0)

    combined, index = cc.combine_curve_matrices(tmp_path, side="right")

    assert combined.shape == (ROWS, 10)
    assert len(index) == 10


def test_columns_appear_in_trial_order_then_stride_order(cc, tmp_path):
    """The silent-corruption case. Each source column was written as a unique
    constant, so the combined column values prove the ordering."""
    _write(tmp_path / "S-T01_right.csv", 2, 100.0)     # columns 100, 101
    _write(tmp_path / "S-T02_right.csv", 2, 200.0)     # columns 200, 201

    combined, _index = cc.combine_curve_matrices(tmp_path, side="right")

    assert list(combined[0, :]) == [100.0, 101.0, 200.0, 201.0]


def test_trials_are_sorted_naturally_not_lexically(cc, tmp_path):
    """'T10' must not sort before 'T2'. Lexical order would silently reorder
    a participant's session."""
    _write(tmp_path / "S-T2_right.csv", 1, 200.0)
    _write(tmp_path / "S-T10_right.csv", 1, 1000.0)

    combined, index = cc.combine_curve_matrices(tmp_path, side="right")

    assert list(combined[0, :]) == [200.0, 1000.0]
    assert [entry["trial"] for entry in index] == ["S-T2", "S-T10"]


def test_index_records_the_origin_of_every_column(cc, tmp_path):
    """Plain concatenation loses which trial a stride came from. The sidecar
    is what makes a pooled analysis auditable afterwards."""
    _write(tmp_path / "S-T01_right.csv", 2, 100.0)
    _write(tmp_path / "S-T02_right.csv", 3, 200.0)

    _combined, index = cc.combine_curve_matrices(tmp_path, side="right")

    assert index[0] == {"column": 1, "trial": "S-T01", "stride_in_trial": 1}
    assert index[2] == {"column": 3, "trial": "S-T02", "stride_in_trial": 1}
    assert index[-1] == {"column": 5, "trial": "S-T02", "stride_in_trial": 3}


def test_a_trial_with_a_different_row_count_is_rejected(cc, tmp_path):
    """Row count encodes the coordinate list. Concatenating a 36-coordinate
    export with a 38-coordinate one would misalign every coordinate below the
    divergence while still producing a loadable file."""
    _write(tmp_path / "S-T01_right.csv", 2, 100.0)
    _write(tmp_path / "S-T02_right.csv", 2, 200.0, rows=3636)

    # Matches this module's own wording, not numpy's. An earlier version
    # asserted on "3636", which appears in np.hstack's shape-mismatch message
    # too -- so it passed with the guard removed and tested nothing.
    with pytest.raises(ValueError, match="cannot be pooled"):
        cc.combine_curve_matrices(tmp_path, side="right")


def test_sides_are_never_mixed(cc, tmp_path):
    _write(tmp_path / "S-T01_right.csv", 2, 100.0)
    _write(tmp_path / "S-T01_left.csv", 2, 900.0)

    combined, index = cc.combine_curve_matrices(tmp_path, side="right")

    assert combined.shape[1] == 2
    assert all(entry["trial"].endswith("T01") for entry in index)
    assert list(combined[0, :]) == [100.0, 101.0]


def test_prefix_filter_selects_one_pipeline(cc, tmp_path):
    """Three routes write into the same directory in this project. Combining
    across them would pool incomparable kinematics."""
    _write(tmp_path / "CK-CK-001_right.csv", 2, 100.0)
    _write(tmp_path / "XT-XT-001_right.csv", 2, 700.0)

    combined, _index = cc.combine_curve_matrices(tmp_path, side="right", prefix="CK-")

    assert combined.shape[1] == 2
    assert list(combined[0, :]) == [100.0, 101.0]


def test_no_matching_files_raises_rather_than_writing_an_empty_matrix(cc, tmp_path):
    with pytest.raises(FileNotFoundError, match="No curve files"):
        cc.combine_curve_matrices(tmp_path, side="right")


def test_written_matrix_round_trips_with_the_same_values(cc, tmp_path):
    _write(tmp_path / "S-T01_right.csv", 3, 100.0)
    out = tmp_path / "combined_right.csv"

    combined, index = cc.combine_curve_matrices(tmp_path, side="right")
    cc.write_combined(out, combined, index)

    reloaded = np.loadtxt(out, delimiter=",", ndmin=2)
    assert reloaded.shape == combined.shape
    assert np.allclose(reloaded, combined)


def test_written_matrix_has_no_header_row(cc, tmp_path):
    """Their matrix_general.m reads positionally and hard-codes row indices.
    A header would shift every one of them by a line."""
    _write(tmp_path / "S-T01_right.csv", 2, 100.0)
    out = tmp_path / "combined_right.csv"

    combined, index = cc.combine_curve_matrices(tmp_path, side="right")
    cc.write_combined(out, combined, index)

    first_field = out.read_text().splitlines()[0].split(",")[0]
    float(first_field)          # raises if a header was written


def test_index_sidecar_is_written_alongside(cc, tmp_path):
    _write(tmp_path / "S-T01_right.csv", 2, 100.0)
    out = tmp_path / "combined_right.csv"

    combined, index = cc.combine_curve_matrices(tmp_path, side="right")
    written = cc.write_combined(out, combined, index)

    sidecar = Path(written["index_path"])
    assert sidecar.is_file()
    lines = sidecar.read_text().splitlines()
    assert lines[0] == "column,trial,stride_in_trial"
    assert lines[1] == "1,S-T01,1"


# -- Duplicate detection (2026-08-26) ------------------------------------
# A real case: CK-001 was exported twice under different filenames after the
# session prefix was shortened. Both files hold the same strides. Pooling them
# double-counts that trial with the correct row count, the expected shape and
# no error -- the silent corruption this module has to refuse.


def test_content_identical_files_are_refused(cc, tmp_path):
    """Naming cannot catch this: the two filenames share no common stem. Only
    the contents prove they are the same trial's strides."""
    _write(tmp_path / "sess-T01_right.csv", 3, 100.0)
    duplicate = tmp_path / "OpenCapData_long_prefix-T01_right.csv"
    duplicate.write_bytes((tmp_path / "sess-T01_right.csv").read_bytes())

    with pytest.raises(ValueError, match="same strides"):
        cc.combine_curve_matrices(tmp_path, side="right")


def test_the_duplicate_error_names_both_files(cc, tmp_path):
    """The user has to know which one to delete, so both names appear."""
    _write(tmp_path / "sess-T01_right.csv", 2, 100.0)
    duplicate = tmp_path / "old-T01_right.csv"
    duplicate.write_bytes((tmp_path / "sess-T01_right.csv").read_bytes())

    with pytest.raises(ValueError) as caught:
        cc.combine_curve_matrices(tmp_path, side="right")

    message = str(caught.value)
    assert "sess-T01_right.csv" in message
    assert "old-T01_right.csv" in message


def test_genuinely_different_trials_are_not_flagged(cc, tmp_path):
    """The guard must not fire on a normal session. Two trials that happen to
    have the same stride count are still different data."""
    _write(tmp_path / "S-T01_right.csv", 3, 100.0)
    _write(tmp_path / "S-T02_right.csv", 3, 200.0)

    combined, index = cc.combine_curve_matrices(tmp_path, side="right")

    assert combined.shape[1] == 6
    assert len({entry["trial"] for entry in index}) == 2


def test_duplicates_may_be_resolved_by_keeping_the_newest(cc, tmp_path):
    """An escape hatch for exactly the observed case -- a stale export left
    behind by a naming change. Off by default: silently dropping a file is
    the wrong default when the alternative is a corrupted pool."""
    import time
    old = tmp_path / "OpenCapData_long-T01_right.csv"
    _write(old, 2, 100.0)
    time.sleep(0.01)
    new = tmp_path / "sess-T01_right.csv"
    new.write_bytes(old.read_bytes())

    combined, index = cc.combine_curve_matrices(
        tmp_path, side="right", on_duplicate="keep_newest"
    )

    assert combined.shape[1] == 2
    assert {entry["trial"] for entry in index} == {"sess-T01"}


def test_unknown_duplicate_policy_is_rejected(cc, tmp_path):
    _write(tmp_path / "S-T01_right.csv", 1, 100.0)

    with pytest.raises(ValueError, match="on_duplicate"):
        cc.combine_curve_matrices(tmp_path, side="right", on_duplicate="whatever")
