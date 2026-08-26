"""Tests for jointcheck.py -- the 3-way mean +/- SD comparison figure.

Ported from the supervisor's jointcheck.m/stdshade.m. The ribbon statistics
are what these pin: a figure that plots the wrong mean or a mis-scaled band
looks entirely convincing, which is exactly why it needs testing. Layout is
covered only where it carries meaning (one axis per coordinate, nothing
silently dropped).
"""
import importlib.util
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # headless: no display in the test environment

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parent.parent / "jointcheck.py"


@pytest.fixture(scope="module")
def jc():
    spec = importlib.util.spec_from_file_location("jointcheck_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ribbon_is_mean_plus_and_minus_one_sd(jc):
    """stdshade draws mean with a +/-1 SD envelope. Values chosen so the mean
    and SD are exact: {1,3} has mean 2, population SD 1."""
    curves = np.array([[1.0, 1.0, 1.0], [3.0, 3.0, 3.0]])   # 2 strides x 3 points

    mean, lower, upper = jc.ribbon(curves)

    assert mean == pytest.approx([2.0, 2.0, 2.0])
    assert lower == pytest.approx([1.0, 1.0, 1.0])
    assert upper == pytest.approx([3.0, 3.0, 3.0])


def test_ribbon_collapses_to_the_line_for_a_single_stride(jc):
    """One stride has no spread. A band drawn anyway would imply variability
    that was never measured."""
    curves = np.array([[5.0, 6.0, 7.0]])

    mean, lower, upper = jc.ribbon(curves)

    assert mean == pytest.approx([5.0, 6.0, 7.0])
    assert lower == pytest.approx(upper)


def test_ribbon_rejects_an_empty_set(jc):
    with pytest.raises(ValueError, match="no strides"):
        jc.ribbon(np.zeros((0, 101)))


def test_ribbon_uses_population_sd_not_sample_sd(jc):
    """Pins which convention is drawn. Sample SD of {1,3} is 1.414, population
    SD is 1.0 -- a reader comparing band widths across figures needs to know
    which one they are looking at."""
    curves = np.array([[1.0], [3.0]])

    _mean, lower, upper = jc.ribbon(curves)

    assert (upper[0] - lower[0]) == pytest.approx(2.0)      # +/-1.0, not +/-1.414


def test_coordinate_panel_list_matches_the_supervisors_twenty_six(jc):
    """jointcheck.m plots 26 coordinates -- the full set minus pelvis
    translations, mtp and pro_sup. Pinned so the figure stays comparable to
    the ones they already have."""
    assert len(jc.COMPARISON_COORDINATES) == 26
    for absent in ("pelvis_tx", "pelvis_ty", "pelvis_tz",
                   "mtp_angle_r", "mtp_angle_l", "pro_sup_r", "pro_sup_l"):
        assert absent not in jc.COMPARISON_COORDINATES
    for present in ("pelvis_tilt", "knee_angle_r", "arm_flex_l", "lumbar_rotation"):
        assert present in jc.COMPARISON_COORDINATES


def test_figure_has_one_panel_per_requested_coordinate(jc):
    """Nothing silently dropped: a coordinate missing from the grid would read
    as 'the pipelines agree there' rather than 'it was never plotted'."""
    datasets = {
        "A": {"knee_angle_r": np.ones((3, 101)), "hip_flexion_r": np.zeros((3, 101))},
        "B": {"knee_angle_r": np.ones((2, 101)), "hip_flexion_r": np.zeros((2, 101))},
    }

    figure = jc.plot_comparison(datasets, ["knee_angle_r", "hip_flexion_r"])

    drawn = [ax for ax in figure.axes if ax.get_title()]
    assert len(drawn) == 2
    assert {ax.get_title() for ax in drawn} == {"knee_angle_r", "hip_flexion_r"}


def test_a_pipeline_missing_a_coordinate_is_skipped_not_faked(jc):
    """XtoO supplies mtp where the IK path does not. The panel must show the
    pipelines that have data and simply omit the one that does not, rather
    than plotting zeros that look like a measured flatline."""
    datasets = {
        "has_it": {"mtp_angle_r": np.ones((3, 101))},
        "lacks_it": {},
    }

    figure = jc.plot_comparison(datasets, ["mtp_angle_r"])
    axis = next(ax for ax in figure.axes if ax.get_title() == "mtp_angle_r")

    labels = [line.get_label() for line in axis.get_lines()]
    assert "has_it" in labels
    assert "lacks_it" not in labels
