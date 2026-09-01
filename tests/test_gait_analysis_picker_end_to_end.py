"""The whole path: a real trial that fails detection, through to gait cycles.

Every other test covers a piece -- the picker, the model, `manual_steps`, the
provider seam. This covers the join: construct a real `gait_analysis` on a real
trial whose automatic detection genuinely fails, let prominence escalation fail
for real, and check that the picker opens from inside `segment_walking`, that
its frames are the same index space the pipeline uses, and that its events are
the ones segmentation builds cycles from.

**No credentials are needed, contrary to what this file's author first
believed.** `utils.py` runs `API_TOKEN = get_token()` at import time, which
blocks on `getpass` with no `.env`, and that looked like it required an OpenCap
login. It does not: `get_token` reads through `python-decouple`'s `config`,
which checks the environment before any file, so setting `API_TOKEN` to
anything satisfies it. Nothing on this path calls the API -- a downloaded
session is processed entirely from local files -- so the whole pipeline runs
offline with a placeholder token. A real token is only needed to *fetch* a
session.

Skips unless OpenSim and the (gitignored) session data are both present, so the
default suite on base python stays green. That makes the suite two-tier, and
the difference is worth knowing before trusting a green run:

    ~/miniconda3/python.exe -m pytest tests -q
        538 passed, 6 skipped  -- everything except this file

    ~/miniconda3/envs/opencap-processing/python.exe -m pytest tests -q
        544 passed, 0 skipped  -- including this file, against real OpenSim

Only the second actually exercises gait_analysis. pytest was installed into
the opencap-processing environment on 2026-09-01 for exactly this; nothing
else was missing.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "Data"

# Found by the real-data sweep in test_gait_event_picker_real_data.py's sibling
# analysis: 4 of 77 trials fail ordering at every prominence. This is one.
SESSION_GLOB = "OpenCapData_dc490fa4*"
TRIAL = "Trial9"
MODEL = "LaiUhlrich2022_scaled.osim"


@pytest.fixture(scope="module")
def pipeline():
    """The real gait_analysis module, imported against real OpenSim."""
    pytest.importorskip("opensim",
                        reason="needs the opencap-processing environment")
    if not DATA_ROOT.is_dir():
        pytest.skip("Data/ is gitignored and absent in this checkout")

    # Satisfies utils.py's import-time get_token() without a login. See the
    # module docstring: nothing on this path talks to the API.
    os.environ.setdefault("API_TOKEN", "placeholder-no-api-calls-on-this-path")
    sys.path.insert(0, str(REPO_ROOT))
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        return (importlib.import_module("gait_analysis_UCM_fixed"),
                importlib.import_module("gait_event_picker_ui"))
    finally:
        os.chdir(cwd)


@pytest.fixture(scope="module")
def session_dir():
    sessions = list(DATA_ROOT.glob(SESSION_GLOB))
    if not sessions:
        pytest.skip("the known detection-failure session is not in Data/")
    if not (sessions[0] / "MarkerData" / (TRIAL + ".trc")).is_file():
        pytest.skip("%s is not in the session" % TRIAL)
    return sessions[0]


@pytest.fixture(scope="module")
def analysed(pipeline, session_dir):
    """One real trial driven all the way through, with a scripted operator."""
    gait_module, ui = pipeline
    seen = {}

    def scripted_operator(model):
        """Stands in for the human at the window, clicking a clean cycle."""
        motion = model.picker.motion
        seen['calls'] = seen.get('calls', 0) + 1
        seen['frames'] = motion.n_rows
        seen['name'] = motion.name
        seen['signals'] = sorted(motion.signals)
        for event_type, fraction in (
                ('rHS', 0.10), ('lTO', 0.16), ('lHS', 0.30), ('rTO', 0.36),
                ('rHS', 0.50), ('lTO', 0.56), ('lHS', 0.70), ('rTO', 0.76),
                ('rHS', 0.90)):
            model.select(event_type)
            model.pick_at(float(int(motion.n_rows * fraction)))

    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        analysis = gait_module.gait_analysis(
            str(session_dir), TRIAL, 0.0, 0.0, leg='r', n_gait_cycles=-1,
            allow_manual_entry=True, modelName=MODEL,
            manual_event_provider=ui.make_manual_event_provider(
                show=scripted_operator))
    finally:
        os.chdir(cwd)
    return analysis, seen


def test_the_picker_is_opened_from_segment_walking(analysed):
    """Automatic detection really fails on this trial -- prominence escalation
    runs 0.3, 0.25, 0.2 and none of them order correctly -- so reaching the
    picker is the pipeline's own decision, not the test's."""
    _analysis, seen = analysed

    assert seen.get('calls') == 1


def test_the_picker_gets_the_pipelines_own_index_space(analysed):
    """The single most dangerous thing to get wrong: events are frame indices,
    so a picker over a different frame space silently places them elsewhere."""
    analysis, seen = analysed

    assert seen['frames'] == len(analysis.markerDict['time'])


def test_the_picker_gets_the_trials_identity_and_signals(analysed):
    _analysis, seen = analysed

    assert seen['name'] == TRIAL
    assert seen['signals'] == ['l_calc', 'l_toe', 'r_calc', 'r_toe']


def test_the_picked_events_are_what_segmentation_used(analysed):
    """Cycles must start on heel strikes the operator actually picked."""
    analysis, _seen = analysed

    starts = set(analysis.gaitEvents['ipsilateralIdx'][:, 0].tolist())

    assert starts, "no gait cycles were segmented"
    assert starts.issubset(set(analysis.rhs))


def test_left_and_right_events_land_in_their_own_slots(analysed):
    """Edit #13's failure mode, checked on real segmented output: the
    ipsilateral (right) column must hold right toe-offs and the contralateral
    column left ones. The swap put left heel-strikes in the right toe-off slot
    and corrupted every downstream metric while still looking plausible."""
    analysis, _seen = analysed

    ipsi = analysis.gaitEvents['ipsilateralIdx']
    contra = analysis.gaitEvents['contralateralIdx']

    assert analysis.gaitEvents['ipsilateralLeg'] == 'r'
    for cycle in ipsi:
        assert cycle[0] in analysis.rhs        # heel strike, right
        assert cycle[1] in analysis.rto        # toe off, right
        assert cycle[2] in analysis.rhs        # heel strike, right
    for cycle in contra:
        assert cycle[0] in analysis.lto        # toe off, left
        assert cycle[1] in analysis.lhs        # heel strike, left


def test_the_trial_actually_produces_cycles(analysed):
    """The point of the whole fallback chain: a trial that automatic detection
    could not segment now segments."""
    analysis, _seen = analysed

    assert analysis.nGaitCycles >= 1


# -- the review fixes, exercised rather than grepped ------------------------
# These replace source-text assertions. Grepping for a line proves the line is
# present, not that the behaviour it was meant to produce actually happens, and
# every one of these paths runs through real segment_walking.


def _build(pipeline, session_dir, **kwargs):
    gait_module, _ui = pipeline
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        return gait_module.gait_analysis(
            str(session_dir), TRIAL, 0.0, 0.0, n_gait_cycles=-1,
            modelName=MODEL, **kwargs)
    finally:
        os.chdir(cwd)


def test_auto_trim_runs_before_the_picker_opens(analysed):
    """The chain is prominence escalation -> auto-trim -> a human. A human is
    only worth interrupting once the machine has run out of ideas; this used to
    open the window as soon as peak detection failed, so trials auto-trim would
    have segmented on its own still stopped and waited for someone."""
    analysis, _seen = analysed

    assert analysis.usedAutoTrim is True, "the picker pre-empted auto-trim"
    assert analysis.nAutoTrims > 0


def test_declining_fails_with_the_machines_reason_not_the_operators(
        pipeline, session_dir):
    """There is no rung four. Auto-trim has already given up by the time
    anyone is asked, so declining fails the trial with the reason the machine
    gave -- not a message blaming the person for not picking, and not a tally
    of zeros quoted back at them."""
    _gait_module, ui = pipeline
    declined = []

    def operator_cancels(model):
        declined.append(True)
        model.cancel()

    with pytest.raises(Exception) as caught:
        _build(pipeline, session_dir, leg='r', allow_manual_entry=True,
               manual_event_provider=ui.make_manual_event_provider(
                   show=operator_cancels))

    assert declined == [True], "the picker never opened"
    message = str(caught.value)
    assert "Auto-trim" in message or "Automatic detection" in message, (
        "the failure did not carry the machine's reason: " + message)
    assert "heel strikes" in message, (
        "the reason does not say what the machine actually found: " + message)
    assert "Picked so far" not in message, (
        "a tally of zeros was quoted back at an operator who declined")


def test_picking_one_leg_under_auto_says_so(pipeline, session_dir):
    """leg='auto' is the DEFAULT and its guard fires first, so without a
    manual-entry branch there an operator who picked one leg was told to check
    marker data quality and never heard about their own picks."""
    _gait_module, ui = pipeline

    def picks_left_only(model):
        for event_type, fraction in (('lHS', 0.2), ('lTO', 0.3),
                                     ('lHS', 0.6), ('lTO', 0.7)):
            model.select(event_type)
            model.pick_at(float(int(model.picker.motion.n_rows * fraction)))

    with pytest.raises(Exception) as caught:
        _build(pipeline, session_dir, leg='auto', allow_manual_entry=True,
               manual_event_provider=ui.make_manual_event_provider(
                   show=picks_left_only))

    message = str(caught.value)
    assert "only one leg" in message
    assert "Picked so far" in message
    assert "marker data quality" not in message


def test_a_window_that_never_opens_does_not_pass_as_a_decline(pipeline,
                                                              session_dir):
    """The silent failure: plt.show() returns immediately under a
    non-interactive backend, and an empty picker reads as a decline. This must
    surface as an error naming the cause, not vanish into auto-trim."""
    _gait_module, ui = pipeline

    with pytest.raises(RuntimeError, match="never opened"):
        _build(pipeline, session_dir, leg='r', allow_manual_entry=True,
               manual_event_provider=ui.make_manual_event_provider(
                   show=lambda model: None))


def test_auto_trim_keeps_the_picker_signals_in_step(pipeline, session_dir):
    """trimend is cumulative and shortens markerDict every call. It stashes the
    signals it recomputes, so a picker built after auto-trim pairs trimmed
    times with trimmed signals. Left stale, MarkerTimeline now refuses the
    mismatch -- so reaching the picker at all proves they stayed in step."""
    gait_module, ui = pipeline
    opened = {}

    def inspect(model):
        motion = model.picker.motion
        opened['frames'] = motion.n_rows
        opened['lengths'] = {name: len(values)
                             for name, values in motion.signals.items()}
        model.cancel()

    with pytest.raises(Exception):
        _build(pipeline, session_dir, leg='r', allow_manual_entry=True,
               manual_event_provider=ui.make_manual_event_provider(show=inspect))

    assert opened, "the picker never opened, so nothing was checked"
    assert set(opened['lengths'].values()) == {opened['frames']}, (
        "signal lengths %s do not match the %d frames handed over"
        % (opened['lengths'], opened['frames']))
