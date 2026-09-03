"""Tests for trial_scores.py -- GDI and the synergy index for one trial.

The synergy path needs OpenSim for its Jacobian, so it is driven against a
fake task function; everything else runs on synthetic curve matrices. What is
pinned is that the numbers reach the report in a shape the table renderer can
format, and that an absent score is visibly absent rather than a zero.
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
def mod():
    return _load("trial_scores_under_test", "trial_scores.py")


@pytest.fixture(scope="module")
def curves():
    return _load("curves_for_scores_tests", "curve_features.py")


@pytest.fixture(scope="module")
def formatting():
    return _load("formatting_for_scores_tests", "report_formatting.py")


@pytest.fixture(scope="module")
def row_order(curves):
    return curves.exported_row_order()


def _matrix_file(tmp_path, row_order, name="t_right.csv", n_strides=4):
    matrix = np.vstack([np.full((101, n_strides), float(i))
                        for i in range(len(row_order))])
    path = tmp_path / name
    np.savetxt(path, matrix, delimiter=",")
    return path


# -- the UCM configuration -------------------------------------------------


def test_the_configuration_is_the_eighteen_documented_dofs(mod):
    """ucm.py's intended formulation: pelvis orientation, lumbar, both legs.
    Excludes the pinned root translations, the toe joints (frozen in both
    methodologies) and the upper limb (saturated on the IMU route)."""
    assert len(mod.UCM_COORDINATES) == 18
    assert not any("_tx" in c or "_ty" in c or "_tz" in c
                   for c in mod.UCM_COORDINATES)
    assert not any("mtp" in c or "arm" in c or "elbow" in c
                   for c in mod.UCM_COORDINATES)
    assert "lumbar_extension" in mod.UCM_COORDINATES


def test_joint_cycles_come_back_phase_stride_dof(mod, tmp_path, row_order):
    """ucm.analyse_cycle's contract. Any other axis order silently decomposes
    the wrong thing."""
    path = _matrix_file(tmp_path, row_order, n_strides=6)

    cycles = mod.joint_cycles_from_curves(path)

    assert cycles.shape == (101, 6, 18)


def test_each_dof_carries_its_own_coordinate(mod, tmp_path, row_order):
    """The check that catches a misordered configuration: every DOF slice must
    hold that coordinate's own marker value."""
    path = _matrix_file(tmp_path, row_order)

    cycles = mod.joint_cycles_from_curves(path)

    for index, name in enumerate(mod.UCM_COORDINATES):
        assert np.all(cycles[:, :, index] == float(row_order.index(name)))


def test_an_export_missing_a_configuration_coordinate_says_which(mod, tmp_path,
                                                                 row_order):
    trimmed = [c for c in row_order if c != "lumbar_bending"]
    matrix = np.vstack([np.full((101, 3), float(i))
                        for i in range(len(trimmed))])
    path = tmp_path / "short.csv"
    np.savetxt(path, matrix, delimiter=",")

    with pytest.raises(Exception) as caught:
        mod.joint_cycles_from_curves(path, row_order=trimmed)

    assert "lumbar_bending" in str(caught.value)


# -- what reaches the report -----------------------------------------------


def test_every_cell_is_formattable_by_the_report(mod, formatting):
    """The rows are injected straight into shaped_results["metrics"], which
    the PDF renders through format_metric_value. A bare float there raises
    AttributeError at export time, after the whole pipeline has re-run."""
    rows = mod.format_for_report(
        {"right": {"mean": 82.9, "sd": 1.0, "n_strides": 4},
         "left": {"mean": 88.8, "sd": 1.3, "n_strides": 5},
         "feature_set": "reduced6"},
        {"mean_delta_v": 0.296, "task_variable": "pelvis-relative centre of mass",
         "phases_with_synergy": 83, "n_phases": 101, "n_dof": 18,
         "dim_ucm": 15, "dim_ort": 3})

    for name, row in rows.items():
        for key in ("r", "l"):
            formatting.format_metric_value(row[key])      # must not raise
        formatting.format_symmetry_value(row["symmetry"])


def test_a_stride_count_is_not_printed_as_a_decimal(mod, formatting):
    """format_metric_value applies "%.2f" to any int or float, so a count
    passed as a number renders as "4.00"."""
    rows = mod.format_for_report(
        {"right": {"mean": 80.0, "sd": None, "n_strides": 4},
         "left": None, "feature_set": "reduced6"}, None)

    rendered = formatting.format_metric_value(rows["GDI: strides scored"]["r"])

    assert rendered.strip() == "4"


def test_the_synergy_row_states_its_task_variable(mod):
    """The ranking between methodologies reverses with this choice, so a bare
    dV is not interpretable without it."""
    rows = mod.format_for_report(None, {
        "mean_delta_v": 0.3, "task_variable": "pelvis-relative centre of mass",
        "phases_with_synergy": 83, "n_phases": 101, "n_dof": 18,
        "dim_ucm": 15, "dim_ort": 3})

    assert "Synergy: task" in rows
    assert rows["Synergy: task"]["r"]["value"] == "pelvis-relative centre of mass"


def test_a_column_that_does_not_apply_reads_blank_not_unavailable(mod,
                                                                  formatting):
    """"not available" implies something was attempted and failed. Symmetry is
    simply undefined for GDI."""
    rows = mod.format_for_report(
        {"right": {"mean": 80.0, "sd": None, "n_strides": 4},
         "left": None, "feature_set": "reduced6"}, None)

    rendered = formatting.format_symmetry_value(rows["GDI (reduced6)"]["symmetry"])

    assert "not available" not in rendered
    assert rendered.strip() == ""


def test_no_scores_produces_no_rows(mod):
    """An absent score must leave the table as it was, not add empty rows that
    look like failed measurements."""
    assert mod.format_for_report(None, None) == {}


def test_a_synergy_without_a_value_produces_no_rows(mod):
    """A zero or NaN dV in a report table is indistinguishable from a computed
    result -- the same reason methodology_comparison refused to emit one."""
    assert mod.format_for_report(None, {"mean_delta_v": None}) == {}


def test_a_missing_side_is_reported_as_unavailable_not_zero(mod, formatting):
    rows = mod.format_for_report(
        {"right": {"mean": 80.0, "sd": None, "n_strides": 4},
         "left": None, "feature_set": "reduced6"}, None)

    rendered = formatting.format_metric_value(rows["GDI (reduced6)"]["l"])

    assert "not available" in rendered
    assert "0" not in rendered


def test_the_feature_set_is_named_in_the_row(mod):
    """Scores are not comparable across feature sets, so the row must say
    which one produced them."""
    rows = mod.format_for_report(
        {"right": {"mean": 80.0, "sd": None, "n_strides": 4},
         "left": None, "feature_set": "reduced4"}, None)

    assert any("reduced4" in name for name in rows)


# -- the headline block and its figures ------------------------------------


@pytest.fixture(scope="module")
def export():
    import matplotlib
    matplotlib.use("Agg")
    return _load("report_export_for_scores_tests", "report_export.py")


def _scores():
    return ({"right": {"mean": 82.9, "sd": 0.9, "n_strides": 4,
                       "per_stride": [82.0, 83.1, 83.4, 83.1]},
             "left": {"mean": 88.8, "sd": 1.3, "n_strides": 5,
                      "per_stride": [87.5, 88.9, 89.4, 89.0, 89.2]},
             "feature_set": "reduced6"},
            {"mean_delta_v": 0.296, "task_variable": "pelvis-relative centre of mass",
             "phases_with_synergy": 83, "n_phases": 101, "n_dof": 18,
             "dim_ucm": 15, "dim_ort": 3,
             "per_phase": {"delta_v": [0.1, -0.2, 0.4], "v_ucm": [1.0, 0.9, 1.2],
                           "v_ort": [0.9, 1.1, 0.8]}})


def test_the_summary_names_the_normative_meaning_of_the_number(mod):
    """GDI is only interpretable if the reader knows 100 is the control mean
    and 10 points is one SD. A bare 82.9 says nothing on its own."""
    gdi, synergy = _scores()

    summary = mod.summary_for_report(gdi, synergy)

    assert "100" in summary["gdi"]["basis"]
    assert "standard deviation" in summary["gdi"]["basis"]


def test_the_summary_shows_the_stride_spread_not_just_the_mean(mod):
    gdi, _ = _scores()

    summary = mod.summary_for_report(gdi, None)

    assert "SD" in summary["gdi"]["right_display"]
    assert "4 strides" in summary["gdi"]["right_display"]


def test_the_summary_carries_the_raw_detail_the_figures_need(mod):
    """The display strings cannot be plotted; the figures need per-stride and
    per-phase values."""
    gdi, synergy = _scores()

    summary = mod.summary_for_report(gdi, synergy)

    assert summary["gdi_detail"]["right"]["per_stride"]
    assert summary["synergy_detail"]["per_phase"]["delta_v"]


def test_the_summary_page_is_skipped_when_there_is_nothing_to_show(export):
    """An empty headline page is worse than none -- it reads as a measurement
    that failed."""
    assert export._build_summary_page({}) is None
    assert export._build_summary_page(None) is None


def test_the_gdi_figure_draws_the_normative_band_and_every_stride(export):
    gdi, _ = _scores()

    figure = export._build_gdi_figure(gdi)

    axis = figure.axes[0]
    # 100 +/- 1 SD and the 1-2 SD band, plus the control-mean line.
    assert len(axis.patches) >= 2
    labels = [t.get_text() for t in axis.get_xticklabels()]
    assert labels == ["Right", "Left"]


def test_the_gdi_figure_is_skipped_without_scores(export):
    assert export._build_gdi_figure(None) is None
    assert export._build_gdi_figure({"right": None, "left": None}) is None


def test_the_synergy_figure_plots_the_cycle_not_just_the_mean(export):
    """The cycle mean says whether a synergy is present on average; the curve
    says where. A trial can average positive while being negative through
    single support."""
    _, synergy = _scores()

    figure = export._build_synergy_figure(synergy)

    assert len(figure.axes) == 2                     # dV, and the decomposition
    assert figure.axes[1].get_xlabel() == "Gait cycle (%)"


def test_the_synergy_figure_names_its_task_variable_in_the_title(export):
    _, synergy = _scores()

    title = export._build_synergy_figure(synergy).axes[0].get_title()

    assert "pelvis-relative centre of mass" in title


def test_the_synergy_figure_is_skipped_without_per_phase_data(export):
    assert export._build_synergy_figure({"mean_delta_v": 0.3}) is None
    assert export._build_synergy_figure(None) is None
