"""Tests for rerun_survey.py.

The real gait_analysis needs OpenSim, which this environment does not have, so
every test drives a fake module through the same `gait_module` seam
`clinician_gui.run_pipeline` uses. What is being tested is the survey's own
logic -- the three-way verdict, the never-raise contract, the manifest shape --
not segmentation, which has its own coverage.
"""
import csv
import importlib.util
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location(
        "rerun_survey_under_test", REPO_ROOT / "rerun_survey.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_gait_module(used_auto_trim=False, n_auto_trims=0, n_cycles=5,
                      cadence=128.0, raises=None, instrumented=True):
    """A stand-in for gait_analysis_UCM_fixed with just the surface the
    survey touches."""
    class _FakeGaitAnalysis:
        def __init__(self, *args, **kwargs):
            if raises is not None:
                raise raises
            self.nGaitCycles = n_cycles
            if instrumented:
                self.usedAutoTrim = used_auto_trim
                self.nAutoTrims = n_auto_trims

        def compute_cadence(self):
            if cadence is None:
                raise ValueError("not enough cycles for a cadence")
            return cadence, "steps/min"

    return types.SimpleNamespace(gait_analysis=_FakeGaitAnalysis)


# -- The three-way verdict -------------------------------------------------
# The whole point of the survey. A trial that took the auto-trim path went
# through the swapped trimend and is corrupt; one that never did is clean;
# one that cannot be processed at all is neither.


def test_a_trial_that_used_auto_trim_is_corrupt(mod):
    row = mod.survey_trial("s", "T1", "m.osim", "r",
                           _fake_gait_module(used_auto_trim=True, n_auto_trims=7))

    assert row["verdict"] == mod.CORRUPT
    assert row["used_auto_trim"] is True
    assert row["n_auto_trims"] == 7
    assert row["error"] is None


def test_a_trial_that_never_auto_trimmed_is_clean(mod):
    row = mod.survey_trial("s", "T1", "m.osim", "r",
                           _fake_gait_module(used_auto_trim=False))

    assert row["verdict"] == mod.CLEAN
    assert row["used_auto_trim"] is False
    assert row["n_auto_trims"] == 0


def test_a_trial_that_cannot_be_segmented_is_its_own_bucket(mod):
    row = mod.survey_trial(
        "s", "T1", "m.osim", "r",
        _fake_gait_module(raises=Exception("no heel-strike events detected")))

    assert row["verdict"] == mod.FAILED
    # Not folded into clean: an unprocessable trial needs the manual event
    # picker, not a re-run, and the two must stay distinguishable.
    assert row["verdict"] != mod.CLEAN
    assert "no heel-strike events" in row["error"]


# -- The never-raise contract ----------------------------------------------
# A survey that stops at the first bad recording cannot survey an archive.


def test_a_failing_trial_does_not_stop_the_survey(mod):
    rows = mod.survey_session(
        "s", "m.osim", _fake_gait_module(raises=KeyError("r_calc_study")),
        trial_names=["T1", "T2", "T3"])

    assert len(rows) == 6  # three trials x two legs
    assert all(row["verdict"] == mod.FAILED for row in rows)


def test_a_native_style_failure_is_recorded_not_propagated(mod):
    """gait_analysis can raise things that are not Exception subclasses on the
    OpenSim path. Those still belong in the manifest as a failed row."""
    class _NotAnException(BaseException):
        pass

    row = mod.survey_trial("s", "T1", "m.osim", "r",
                           _fake_gait_module(raises=_NotAnException("aborted")))

    assert row["verdict"] == mod.FAILED
    assert "_NotAnException" in row["error"]


def test_ctrl_c_stops_the_survey_rather_than_being_logged(mod):
    """The one thing the broad except must not swallow. This sweeps a whole
    archive; an operator who interrupts it has to be able to stop it."""
    with pytest.raises(KeyboardInterrupt):
        mod.survey_trial("s", "T1", "m.osim", "r",
                         _fake_gait_module(raises=KeyboardInterrupt()))


# -- Instrumentation is required, not optional -----------------------------


def test_an_uninstrumented_build_is_a_failed_row_not_a_clean_one(mod):
    """A checkout predating the 2026-08-27 instrumentation cannot answer the
    question. Reporting it as clean would silently drop corrupt trials from
    the re-run set -- the exact failure this survey exists to prevent."""
    row = mod.survey_trial("s", "T1", "m.osim", "r",
                           _fake_gait_module(instrumented=False))

    assert row["verdict"] == mod.FAILED
    assert "usedAutoTrim" in row["error"]


# -- Diagnostics are recorded, never enforced ------------------------------
# The non-gait guardrail was removed 2026-08-27. These columns exist so an
# outlier is visible and sortable; nothing here may refuse a trial.


def test_a_one_cycle_trial_is_still_surveyed_and_not_rejected(mod):
    row = mod.survey_trial("s", "T1", "m.osim", "r",
                           _fake_gait_module(n_cycles=1, cadence=12.0))

    assert row["verdict"] == mod.CLEAN
    assert row["n_gait_cycles"] == 1
    assert row["cadence_steps_per_min"] == 12.0


def test_an_uncomputable_cadence_leaves_the_cell_empty(mod):
    row = mod.survey_trial("s", "T1", "m.osim", "r",
                           _fake_gait_module(cadence=None))

    assert row["cadence_steps_per_min"] is None
    assert row["verdict"] == mod.CLEAN  # a missing diagnostic is not a failure


# -- Manifest shape --------------------------------------------------------


def test_both_legs_are_surveyed_independently(mod):
    """A trial can be clean on one leg and corrupt on the other: each leg is
    a separate gait_analysis instance making its own trip through the loop."""
    rows = mod.survey_session("s", "m.osim", _fake_gait_module(),
                              trial_names=["T1"])

    assert [row["leg"] for row in rows] == ["r", "l"]


def test_the_manifest_round_trips_with_a_header(mod, tmp_path):
    rows = mod.survey_session(
        "s", "m.osim", _fake_gait_module(used_auto_trim=True, n_auto_trims=3),
        trial_names=["T1"])
    path = mod.write_manifest(rows, tmp_path / "out" / "rerun_manifest.csv")

    with open(path, newline="", encoding="utf-8") as handle:
        read_back = list(csv.DictReader(handle))

    assert list(read_back[0].keys()) == list(mod.SURVEY_FIELDS)
    assert read_back[0]["verdict"] == mod.CORRUPT
    assert read_back[0]["n_auto_trims"] == "3"


def test_the_summary_counts_every_bucket(mod):
    rows = [
        {"verdict": mod.CORRUPT}, {"verdict": mod.CORRUPT},
        {"verdict": mod.CLEAN}, {"verdict": mod.FAILED},
    ]

    assert mod.summarise(rows) == {mod.CORRUPT: 2, mod.CLEAN: 1, mod.FAILED: 1}


# -- Trial discovery -------------------------------------------------------


def test_trials_are_discovered_from_the_ik_results_in_natural_order(mod, tmp_path):
    ik_dir = tmp_path / "OpenSimData" / "Kinematics"
    ik_dir.mkdir(parents=True)
    for name in ("T10", "T2", "T1"):
        (ik_dir / f"{name}.mot").write_text("")

    # T10 follows T2, not T1 -- a lexical sort would reorder the session.
    assert mod.discover_trials(tmp_path) == ["T1", "T2", "T10"]


def test_a_session_without_ik_results_says_so(mod, tmp_path):
    with pytest.raises(FileNotFoundError, match="already have been through conversion"):
        mod.discover_trials(tmp_path)
