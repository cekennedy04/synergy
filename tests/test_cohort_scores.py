"""Tests for cohort_scores.py -- GDI and the synergy index across the cohort.

Only the pure functions are exercised here. Scoring a session needs OpenSim and
a normative reference; the statistics that decide what the cohort report
*claims* need neither, and they are where a wrong answer would be quietest --
a correlation printed from two points, or an asymmetry computed from one limb,
looks exactly like a real result.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def cohort():
    spec = importlib.util.spec_from_file_location(
        "cohort_scores_under_test", REPO_ROOT / "cohort_scores.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# -- _correlate -------------------------------------------------------------


def test_a_clean_linear_relationship_reports_both_measures(cohort):
    result = cohort._correlate([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0])

    assert result["r"] == pytest.approx(1.0)
    assert result["rho"] == pytest.approx(1.0)
    assert result["n"] == 4


def test_two_points_are_not_a_correlation(cohort):
    """Any two distinct points are perfectly collinear, so Pearson returns
    r=1.0 and means nothing by it. The cohort is six participants and can
    reach this after filtering; "not computed" is the honest answer."""
    assert cohort._correlate([1.0, 2.0], [5.0, 9.0]) is None


def test_a_constant_series_is_not_computed_rather_than_nan(cohort):
    """corrcoef on zero variance divides by zero. A nan reaching a clinical
    report reads as a broken number; absent reads as what it is."""
    assert cohort._correlate([3.0, 3.0, 3.0, 3.0], [1.0, 2.0, 3.0, 4.0]) is None
    assert cohort._correlate([1.0, 2.0, 3.0, 4.0], [7.0, 7.0, 7.0, 7.0]) is None


def test_non_finite_pairs_are_dropped_not_propagated(cohort):
    """A missing synergy index arrives as nan. Dropping the pair keeps the
    remaining points usable; propagating it would void the whole correlation."""
    result = cohort._correlate([1.0, 2.0, 3.0, 4.0, np.nan],
                               [2.0, 4.0, 6.0, 8.0, 5.0])

    assert result["n"] == 4, "the nan pair must be dropped, not counted"
    assert result["r"] == pytest.approx(1.0)


def test_dropping_non_finite_pairs_can_take_it_below_the_minimum(cohort):
    """Filtering happens before the size check, not after -- otherwise three
    rows containing two nans would be treated as three points."""
    assert cohort._correlate([1.0, np.nan, np.nan, 4.0],
                             [2.0, 4.0, 6.0, 8.0]) is None


# -- _participant_correlation -----------------------------------------------


def test_each_participant_counts_once_however_many_limbs_they_have(cohort):
    """Left and right from one person are not two independent observations.
    With six participants, counting limbs doubles the apparent n and tightens
    every p-value on data that has not gained a subject."""
    paired = [
        {"participant": "A", "gdi": 80.0, "delta_v": 1.0},
        {"participant": "A", "gdi": 90.0, "delta_v": 3.0},
        {"participant": "B", "gdi": 70.0, "delta_v": 2.0},
        {"participant": "C", "gdi": 60.0, "delta_v": 3.0},
        {"participant": "D", "gdi": 50.0, "delta_v": 4.0},
    ]

    result = cohort._participant_correlation(paired)

    assert result["n"] == 4, "four participants, not five limb rows"


def test_a_participants_limbs_are_averaged_not_taken_first(cohort):
    """A's two limbs average to 85.0/2.0. If the first row were taken instead,
    the series would start at 80.0 and the correlation would differ."""
    paired = [
        {"participant": "A", "gdi": 80.0, "delta_v": 1.0},
        {"participant": "A", "gdi": 90.0, "delta_v": 3.0},
        {"participant": "B", "gdi": 75.0, "delta_v": 1.0},
        {"participant": "C", "gdi": 95.0, "delta_v": 3.0},
    ]

    result = cohort._participant_correlation(paired)

    # A=(85.0, 2.0), B=(75.0, 1.0), C=(95.0, 3.0) -- exactly collinear.
    assert result["r"] == pytest.approx(1.0)
    assert result["n"] == 3


# -- _limb_asymmetry --------------------------------------------------------


def test_asymmetry_is_right_minus_left(cohort):
    rows = [
        {"participant": "A", "side": "right", "gdi": 90.0, "delta_v": 3.0},
        {"participant": "A", "side": "left", "gdi": 80.0, "delta_v": 1.0},
    ]

    result = cohort._limb_asymmetry(rows)

    assert result["A"]["gdi"] == pytest.approx(10.0)
    assert result["A"]["delta_v"] == pytest.approx(2.0)


def test_a_participant_with_one_limb_has_no_asymmetry_to_report(cohort):
    """Not zero -- absent. A one-limb session says nothing about symmetry, and
    a 0.0 in that column is indistinguishable from a measured match."""
    rows = [{"participant": "A", "side": "right", "gdi": 90.0, "delta_v": 3.0}]

    assert cohort._limb_asymmetry(rows) == {}


def test_a_missing_synergy_index_leaves_gdi_asymmetry_intact(cohort):
    """The two metrics fail independently. A session whose model would not load
    still has a usable GDI difference, and dropping the participant entirely
    would lose it."""
    rows = [
        {"participant": "A", "side": "right", "gdi": 90.0, "delta_v": None},
        {"participant": "A", "side": "left", "gdi": 80.0, "delta_v": 1.0},
    ]

    result = cohort._limb_asymmetry(rows)

    assert result["A"]["gdi"] == pytest.approx(10.0)
    assert result["A"]["delta_v"] is None
