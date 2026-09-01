"""Tests for session_report.py -- one PDF per participant, all strides pooled.

The synergy path needs OpenSim, so it is not exercised here; what is pinned is
the pooling, the trial mapping, and the trend plot that makes a drift visible.
"""
import csv
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
def mod():
    return _load("session_report_under_test", "session_report.py")


def _session(tmp_path, conversion="ik", n_trials=3, strides_per_trial=4):
    session = tmp_path / "XsensSession_ZZ"
    curves = session / "GaitCurves"
    curves.mkdir(parents=True)
    total = n_trials * strides_per_trial
    for side in ("right", "left"):
        matrix = np.ones((3838, total))
        np.savetxt(curves / f"XsensSession_ZZ_all-trials_{conversion}_{side}.csv",
                   matrix, delimiter=",")
        index = curves / f"XsensSession_ZZ_all-trials_{conversion}_{side}_index.csv"
        with open(index, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["column", "trial", "stride_in_trial"])
            column = 1
            for trial in range(1, n_trials + 1):
                for stride in range(1, strides_per_trial + 1):
                    writer.writerow([column, f"XsensSession_ZZ-{conversion}-ZZ-{trial:03d}",
                                     stride])
                    column += 1
    return session


# -- finding the pooled matrices -------------------------------------------


def test_the_pooled_matrix_is_found_per_side(mod, tmp_path):
    session = _session(tmp_path)

    paths = mod.pooled_paths(session)

    assert set(paths) == {"right", "left"}
    assert paths["right"]["index"] is not None


def test_the_index_sidecar_is_not_mistaken_for_a_matrix(mod, tmp_path):
    """Both match the same glob; loading the sidecar as a matrix would fail
    far downstream with a shape error naming nothing useful."""
    session = _session(tmp_path)

    paths = mod.pooled_paths(session)

    assert not paths["right"]["matrix"].name.endswith("_index.csv")


def test_an_unpooled_session_says_what_is_missing(mod, tmp_path):
    (tmp_path / "XsensSession_ZZ" / "GaitCurves").mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="pooling happens at the end"):
        mod.pooled_paths(tmp_path / "XsensSession_ZZ")


def test_the_conversion_route_selects_its_own_matrix(mod, tmp_path):
    """ik and xtoo pool separately; mixing them would combine incompatible
    kinematics into one score."""
    session = _session(tmp_path, conversion="xtoo")

    assert mod.pooled_paths(session, "xtoo")
    with pytest.raises(FileNotFoundError):
        mod.pooled_paths(session, "ik")


# -- mapping strides back to trials ----------------------------------------


def test_strides_map_back_to_their_trials(mod, tmp_path):
    session = _session(tmp_path, n_trials=3, strides_per_trial=4)
    index = session / "GaitCurves" / "XsensSession_ZZ_all-trials_ik_right_index.csv"

    trials = mod.stride_trials(index)

    assert len(trials) == 12
    assert len(set(trials)) == 3


def test_a_missing_sidecar_degrades_rather_than_raises(mod, tmp_path):
    """Without it the pooled score is still valid; only the per-trial
    breakdown is unavailable."""
    assert mod.stride_trials(None) == []
    assert mod.stride_trials(tmp_path / "absent.csv") == []


def test_trials_are_ordered_by_session_order_not_first_appearance(mod):
    """The trend plot's x-axis is session order -- that is the axis a drift
    appears on, and a lexical order would put trial 10 before trial 2."""
    per_stride = [80.0, 82.0, 70.0, 72.0, 90.0, 92.0]
    trials = ["T-010", "T-010", "T-002", "T-002", "T-001", "T-001"]

    by_trial = mod.gdi_by_trial(per_stride, trials)

    assert list(by_trial) == ["T-001", "T-002", "T-010"]
    assert by_trial["T-001"] == pytest.approx(91.0)


def test_each_trial_gets_the_mean_of_its_own_strides(mod):
    by_trial = mod.gdi_by_trial([80.0, 90.0, 100.0, 60.0],
                                ["T-001", "T-001", "T-002", "T-002"])

    assert by_trial["T-001"] == pytest.approx(85.0)
    assert by_trial["T-002"] == pytest.approx(80.0)


# -- the trend page --------------------------------------------------------


def test_the_trend_figure_reports_a_correlation_per_side(mod):
    """A monotonic slide across trial order is a measurement problem, not a
    gait finding, so the correlation belongs on the page."""
    scores = {"by_trial": {
        "right": {f"T-{i:03d}": 95.0 - 2.0 * i for i in range(1, 8)},
        "left": {f"T-{i:03d}": 90.0 for i in range(1, 8)}}}

    figure = mod._gdi_trend_figure(scores)

    labels = [t.get_text() for t in figure.axes[0].get_legend().get_texts()]
    assert any("trend r=" in label for label in labels)
    assert any("-1.00" in label or "-0.99" in label for label in labels)


def test_the_trend_figure_is_skipped_without_a_breakdown(mod):
    assert mod._gdi_trend_figure({"by_trial": {}}) is None
    assert mod._gdi_trend_figure({}) is None


def test_the_title_page_states_why_synergy_is_session_level(mod):
    """The methodological point the report exists to make: a four-stride trial
    cannot support a 15/3 variance split."""
    scores = {"session": "XsensSession_ZZ", "conversion": "ik",
              "feature_set": "reduced6",
              "gdi": {"right": {"n_strides": 64}}, "by_trial": {}}

    text = "".join(t.get_text() for t in mod._title_page(scores).axes[0].texts)

    assert "ACROSS strides" in text
    assert "this is the one to quote" in text


def test_a_flat_series_does_not_print_r_equals_nan(mod, recwarn):
    """corrcoef on a constant series divides by zero and returns nan, which
    would reach a clinical report as "r=nan". A flat series has no trend --
    that is a real answer, not a missing one."""
    scores = {"by_trial": {"left": {f"T-{i:03d}": 90.0 for i in range(1, 8)}}}

    figure = mod._gdi_trend_figure(scores)

    labels = [t.get_text() for t in figure.axes[0].get_legend().get_texts()]
    assert not any("nan" in label for label in labels)
    assert any("flat" in label for label in labels)
