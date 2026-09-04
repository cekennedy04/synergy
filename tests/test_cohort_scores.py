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


# -- what the summary discloses, and what it refuses ------------------------


def _session(participant, gdi_by_side, synergy_by_side=None):
    """A minimal session in the shape `cohort_summary` consumes."""
    return {
        "participant": participant,
        "session": f"XsensSession_{participant}",
        "gdi": {side: {"mean": value, "sd": 2.0, "n_strides": 10}
                for side, value in gdi_by_side.items()},
        "synergy": synergy_by_side or {},
        "by_trial": {side: {} for side in gdi_by_side},
    }


def _syn(delta_v, v_ucm=1.0, v_ort=1.0):
    return {"mean_delta_v": delta_v, "mean_delta_v_z": None,
            "mean_v_ucm": v_ucm, "mean_v_ort": v_ort,
            "phases_with_synergy": 1, "n_phases": 2}


def test_the_summary_reports_both_denominators(cohort):
    """GDI is per limb by definition so every row has one; delta-V needs a
    model and a UCM decomposition. A limb missing either is absent from every
    delta_v_* figure. `n_legs` beside a delta_v_mean over fewer limbs reads as
    one cohort and is two, so both counts are reported."""
    sessions = [
        _session("A", {"left": 90.0, "right": 92.0},
                 {"left": _syn(0.5), "right": _syn(0.6)}),
        _session("B", {"left": 88.0, "right": 86.0}),   # no model -> no delta-V
    ]

    summary = cohort.cohort_summary(sessions)

    assert summary["n_legs"] == 4
    assert summary["n_legs_with_delta_v"] == 2
    assert summary["gdi_mean"] == pytest.approx(89.0)      # over all four
    assert summary["delta_v_mean"] == pytest.approx(0.55)  # over the two


def test_a_zero_variance_limb_is_excluded_from_the_variance_fit(cohort):
    """log10(0) is -inf and _correlate drops nonfinite pairs without saying so,
    which would return a plausible correlation over an undisclosed subset. The
    limb is excluded before the log, and the remaining count is reported."""
    sessions = [
        _session("A", {"left": 90.0, "right": 92.0},
                 {"left": _syn(0.5, 1.0, 1.0), "right": _syn(0.6, 2.0, 2.0)}),
        _session("B", {"left": 88.0, "right": 86.0},
                 {"left": _syn(0.4, 0.0, 0.0),      # zero total variance
                  "right": _syn(0.3, 3.0, 1.0)}),
    ]

    summary = cohort.cohort_summary(sessions)

    assert summary["n_legs_with_delta_v"] == 4
    assert summary["n_legs_in_variance_fit"] == 3, (
        "the zero-variance limb must be excluded before the log, and the "
        "reduced denominator reported rather than left to be inferred."
    )


def test_two_candidate_models_are_refused_rather_than_sorted(cohort, tmp_path):
    """Taking the alphabetically-first would build a Jacobian about the wrong
    skeleton -- a plausible wrong synergy index nothing downstream could
    detect. Every session in this study has exactly one, so a second means the
    naming assumption has broken and guessing is not available."""
    model_dir = tmp_path / "OpenSimData" / "Model"
    model_dir.mkdir(parents=True)
    (model_dir / "a_scaled.osim").write_text("", encoding="utf-8")
    (model_dir / "b_scaled.osim").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot tell which"):
        cohort.session_model(tmp_path)


def test_one_model_and_no_model_both_still_work(cohort, tmp_path):
    """The refusal must not turn the ordinary cases into errors."""
    model_dir = tmp_path / "OpenSimData" / "Model"
    model_dir.mkdir(parents=True)
    assert cohort.session_model(tmp_path) is None

    (model_dir / "only_scaled.osim").write_text("", encoding="utf-8")
    assert cohort.session_model(tmp_path).endswith("only_scaled.osim")

    # A calibrated file alongside is ignored, not counted as a second candidate.
    (model_dir / "only_scaled_calibrated.osim").write_text("", encoding="utf-8")
    assert cohort.session_model(tmp_path).endswith("only_scaled.osim")
