"""Tests for session_drift.py.

Synthetic sessions with a drift planted in one variable of one leg, because
the thing being tested is whether a known drift is found and an absent one is
not claimed.
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
    return _load("session_drift_under_test", "session_drift.py")


@pytest.fixture(scope="module")
def gdi():
    return _load("gdi_for_drift_tests", "gdi.py")


@pytest.fixture(scope="module")
def curves():
    return _load("curves_for_drift_tests", "curve_features.py")


@pytest.fixture(scope="module")
def row_order(curves):
    return curves.exported_row_order()


@pytest.fixture
def reference(gdi):
    rng = np.random.default_rng(0)
    length = gdi.REDUCED6.vector_length
    basis = np.linalg.qr(rng.normal(size=(length, 12)))[0].T
    return {"matrix": basis, "control_mean": np.zeros(12),
            "feature_set": gdi.REDUCED6}


def _session(tmp_path, row_order, n_trials=15, drift_per_trial=0.0,
             drift_coordinate="fpa_r", drift_side="right", name="XsensSession_ZZ"):
    """A processed session whose curve exports carry a planted drift."""
    session = tmp_path / name
    curves_dir = session / "GaitCurves"
    curves_dir.mkdir(parents=True)
    for trial in range(1, n_trials + 1):
        for side in ("right", "left"):
            block = np.zeros((len(row_order) * 101, 3))
            for index, coordinate in enumerate(row_order):
                base = float(index)
                if coordinate == drift_coordinate and side == drift_side:
                    base += drift_per_trial * trial
                block[index * 101:(index + 1) * 101, :] = base
            path = curves_dir / f"{name}-ik-T-{trial:03d}_{side}.csv"
            np.savetxt(path, block, delimiter=",")
    return session


# -- finding the trials ----------------------------------------------------


def test_trials_are_read_in_order_not_lexically(mod, tmp_path, row_order):
    session = _session(tmp_path, row_order, n_trials=12)

    _files, numbers = mod.trial_curve_files(session, "right")

    assert numbers == list(range(1, 13))


def test_the_pooled_matrix_is_excluded(mod, tmp_path, row_order):
    """It is the concatenation this module exists to look inside."""
    session = _session(tmp_path, row_order, n_trials=8)
    pooled = session / "GaitCurves" / "XsensSession_ZZ_all-trials_ik_right.csv"
    pooled.write_text("1,2\n")

    files, _numbers = mod.trial_curve_files(session, "right")

    assert all("all-trials" not in f.name for f in files)


def test_an_unprocessed_session_says_so(mod, tmp_path):
    with pytest.raises(FileNotFoundError, match="not been processed"):
        mod.trial_curve_files(tmp_path / "nothing", "right")


# -- the trend itself ------------------------------------------------------


def test_a_planted_drift_is_found_on_the_leg_that_has_it(mod, tmp_path,
                                                         row_order, reference,
                                                         gdi, curves):
    session = _session(tmp_path, row_order, drift_per_trial=1.5,
                       drift_coordinate="fpa_r", drift_side="right")

    report = mod.session_report(session, reference, gdi.REDUCED6, "ik", gdi,
                                curves)

    right = report["sides"]["right"]["variables"]["fpa"]
    assert abs(right["r"]) > 0.99
    assert right["last3"] - right["first3"] == pytest.approx(1.5 * 12, rel=0.05)


def test_the_other_leg_is_not_implicated(mod, tmp_path, row_order, reference,
                                         gdi, curves):
    """Asymmetry is the whole diagnostic value: a side-wide claim from a
    one-sided drift would point at the wrong hardware."""
    session = _session(tmp_path, row_order, drift_per_trial=1.5,
                       drift_side="right")

    report = mod.session_report(session, reference, gdi.REDUCED6, "ik", gdi,
                                curves)

    left = report["sides"]["left"]["variables"]["fpa"]
    assert left["r"] == pytest.approx(0.0, abs=0.01)


def test_a_clean_session_raises_no_alert(mod, tmp_path, row_order, reference,
                                         gdi, curves):
    session = _session(tmp_path, row_order, drift_per_trial=0.0)

    report = mod.session_report(session, reference, gdi.REDUCED6, "ik", gdi,
                                curves)

    assert mod.alerts(report) == []


def test_a_short_session_is_not_given_a_trend(mod, tmp_path, row_order,
                                              reference, gdi, curves):
    """A correlation over three or four trials is not evidence of anything."""
    session = _session(tmp_path, row_order, n_trials=4, drift_per_trial=3.0)

    report = mod.session_report(session, reference, gdi.REDUCED6, "ik", gdi,
                                curves)

    assert "note" in report["sides"]["right"]
    assert mod.alerts(report) == []


def test_a_flat_series_does_not_produce_a_spurious_correlation(mod):
    """np.corrcoef on a constant series is nan, which would sort as a trend."""
    r, slope, first, last = mod.linear_trend([1, 2, 3, 4], [5.0] * 4)

    assert r == 0.0 and slope == 0.0
    assert first == last == 5.0


def test_a_tiny_but_perfectly_monotonic_drift_is_not_flagged(mod, tmp_path,
                                                             row_order,
                                                             reference, gdi,
                                                             curves):
    """A real clean participant showed knee_angle at r = 0.959 over 2.8
    degrees. Correlation alone would mark that, and marks nobody should act on
    train the reader to ignore all of them."""
    session = _session(tmp_path, row_order, drift_per_trial=0.05)

    report = mod.session_report(session, reference, gdi.REDUCED6, "ik", gdi,
                                curves)
    text = mod.format_report(report)

    variable = report["sides"]["right"]["variables"]["fpa"]
    assert abs(variable["r"]) > 0.95        # perfectly monotonic
    assert "*" not in text                  # and still not worth marking
    assert mod.alerts(report) == []


# -- what the alert says ---------------------------------------------------


def test_an_alert_names_the_leading_variable(mod, tmp_path, row_order,
                                             reference, gdi, curves):
    session = _session(tmp_path, row_order, drift_per_trial=4.0,
                       drift_coordinate="fpa_r", drift_side="right")

    report = mod.session_report(session, reference, gdi.REDUCED6, "ik", gdi,
                                curves)
    found = mod.alerts(report)

    assert found and found[0]["side"] == "right"
    assert found[0]["leading_variable"] == "fpa"


def test_the_alert_refuses_to_state_a_cause(mod, tmp_path, row_order,
                                            reference, gdi, curves):
    """Measured on the first two participants: near-identical GDI trends,
    different underlying variables, different mechanisms. This tool must not
    conclude anything."""
    session = _session(tmp_path, row_order, drift_per_trial=4.0)

    text = mod.format_report(
        mod.session_report(session, reference, gdi.REDUCED6, "ik", gdi, curves))

    assert "not its cause" in text


def test_both_legs_are_always_reported(mod, tmp_path, row_order, reference,
                                       gdi, curves):
    """Pooling the legs is exactly what hides a one-sided drift."""
    session = _session(tmp_path, row_order, drift_per_trial=2.0)

    report = mod.session_report(session, reference, gdi.REDUCED6, "ik", gdi,
                                curves)

    assert set(report["sides"]) == {"right", "left"}
