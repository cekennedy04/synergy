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


# -- the synergy index is per limb ------------------------------------------


class _StubScoresModule:
    """Stands in for trial_scores.py, whose synergy path needs OpenSim.

    Records the matrix path it was handed for each call, which is the thing
    worth asserting: not that a number came back, but that each side's number
    was computed from that side's own matrix.
    """

    def __init__(self):
        self.matrices = []

    def synergy_for_trial(self, curve_matrix_path, model_path, **kwargs):
        self.matrices.append(Path(curve_matrix_path).name)
        return {"mean_delta_v": 0.5, "n_phases": 4, "phases_with_synergy": 3,
                "task_variable": "stub", "n_dof": 6, "dim_ucm": 4,
                "dim_ort": 2}


class _StubGdi:
    DEFAULT_FEATURE_SET = "reduced6"

    class _Set:
        name = "reduced6"

    def get_feature_set(self, name):
        return self._Set()

    def load_gdi_reference(self, directory, feature_set, **kwargs):
        return {"feature_set": feature_set}


class _StubCurves:
    def exported_row_order(self):
        return []

    def load_curve_matrix(self, path, row_order=None):
        return np.ones((3838, 4))

    def score_curves(self, matrix, side, reference, feature_set, gdi, row_order):
        return np.array([90.0, 91.0, 92.0, 93.0])


def _stub_collaborators(mod, monkeypatch, scores_stub):
    """Route session_scores' three by-path loads to stubs.

    GDI arithmetic and the UCM computation are covered by their own suites;
    what is under test here is which matrix each side's synergy is built from,
    and that is pure dispatch.
    """
    real_load = mod._load

    def fake_load(name, filename):
        if filename == "trial_scores.py":
            return scores_stub
        if filename == "gdi.py":
            return _StubGdi()
        if filename == "curve_features.py":
            return _StubCurves()
        return real_load(name, filename)

    monkeypatch.setattr(mod, "_load", fake_load)


def test_the_synergy_index_is_keyed_by_side_the_way_gdi_is(mod, tmp_path,
                                                          monkeypatch):
    """GDI is per limb by definition, so the synergy index has to be too.

    While `synergy` was a single unkeyed value, a cohort-level correlation
    could pair a left GDI against a right synergy index and nothing
    downstream could tell. Same shape as `gdi` means the pairing is
    structurally impossible rather than merely documented.
    """
    session = _session(tmp_path)
    stub = _StubScoresModule()
    _stub_collaborators(mod, monkeypatch, stub)

    scores = mod.session_scores(session, reference_dir=tmp_path,
                                model_path="model.osim")

    assert set(scores["synergy"]) == {"right", "left"}
    assert set(stub.matrices) == {
        "XsensSession_ZZ_all-trials_ik_right.csv",
        "XsensSession_ZZ_all-trials_ik_left.csv",
    }, "each side's synergy must come from that side's own pooled matrix"


def test_a_one_sided_session_does_not_borrow_the_other_limbs_matrix(
        mod, tmp_path, monkeypatch):
    """The replaced code read `paths.get("right") or next(iter(paths.values()))`
    and stored the result under a bare `synergy` key. On a session with no
    right side that silently scored whichever limb came first and labelled it
    nothing. Absent is the honest answer; a mislabelled number is not.
    """
    session = _session(tmp_path)
    for stale in (session / "GaitCurves").glob("*_right*"):
        stale.unlink()
    stub = _StubScoresModule()
    _stub_collaborators(mod, monkeypatch, stub)

    scores = mod.session_scores(session, reference_dir=tmp_path,
                                model_path="model.osim")

    assert set(scores["synergy"]) == {"left"}
    assert "right" not in scores["synergy"]
    assert stub.matrices == ["XsensSession_ZZ_all-trials_ik_left.csv"]


def test_no_model_means_no_synergy_rather_than_an_empty_promise(mod, tmp_path,
                                                               monkeypatch):
    """Without an OpenSim model the index cannot be computed at all. The key
    stays absent so a caller cannot iterate an empty dict and conclude the
    session had no synergy."""
    session = _session(tmp_path)
    stub = _StubScoresModule()
    _stub_collaborators(mod, monkeypatch, stub)

    scores = mod.session_scores(session, reference_dir=tmp_path, model_path=None)

    assert scores["synergy"] == {}
    assert stub.matrices == []
