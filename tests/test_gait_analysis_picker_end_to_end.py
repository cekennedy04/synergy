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
        everything except this file, which skips

    ~/miniconda3/envs/opencap-processing/python.exe -m pytest tests -q
        including this file, against real OpenSim

Deliberately no pass/skip counts here. They were quoted as 538/6 and 544/0
until 2026-09-08, by which point the suite had grown past 845 and the numbers
were quietly wrong -- a stale count in a docstring is worse than no count,
because it reads as a check someone can make and fails them silently.

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


def test_a_non_interactive_backend_is_refused_on_the_real_pipeline(
        pipeline, session_dir, monkeypatch):
    """The silent failure this pair of tests exists for: `plt.show()` returns
    immediately under a non-interactive backend, so the operator never sees a
    window and whatever the picker holds is passed off as their answer.
    make_reports.py and make_comparison_figures.py both force Agg process-wide
    at import, so any process that has touched either would hit this.

    Until 2026-09-08 the check that caught it was an emptiness backstop in
    `make_manual_event_provider`, and this test drove it with
    `show=lambda model: None` -- which never called the real `show` at all, so
    it proved the backstop worked and nothing about the path an operator takes.
    Seeding made the backstop partial (see the test below), and moved the
    deterministic guard to `assert_interactive_backend`, which
    `show_picker_window` calls before building anything. So this now runs the
    REAL `show_picker_window` through real `segment_walking`, which is both the
    honest guard and a stronger test than the one it replaces.
    """
    _gait_module, ui = pipeline
    matplotlib = pytest.importorskip("matplotlib")
    monkeypatch.setattr(matplotlib, "get_backend", lambda: "Agg")

    # NOT redundant with test_a_non_interactive_backend_is_refused_before_
    # drawing in test_gait_event_picker_ui.py, which calls show_picker_window
    # directly. The point here is the empty argument list below: it proves the
    # guarded show is what make_manual_event_provider DEFAULTS to and that
    # segment_walking actually reaches it. Keep both -- and note this one runs
    # only in the opencap tier, so the unit copy is CI's only cover.
    with pytest.raises(RuntimeError, match="never opens a window"):
        _build(pipeline, session_dir, leg='r', allow_manual_entry=True,
               manual_event_provider=ui.make_manual_event_provider())


def test_a_never_opened_window_over_a_seed_still_fails_loudly(pipeline,
                                                              session_dir):
    """The residual risk seeding introduced, pinned so it stays loud.

    `build_manual_picker` seeds the picker with what detection found, so on a
    trial where detection found *something* a window that never opened returns
    those seeded events rather than an empty set -- and the emptiness backstop
    cannot tell that from an operator accepting the machine's answer, which is
    a legitimate outcome. The backstop therefore does not fire here.

    What must not follow is a silent pass. This trial seeds ZERO right heel
    strikes (one lHS and one rTO), so it lands on the `len(hsIps) == 0` branch,
    which knows manual entry was involved: it names the leg and quotes the
    counts, and an operator who saw no window is told what was actually held
    rather than being dropped back to auto-trim.

    **That guarantee is currently only half the story, and this test pins the
    half that holds.** Reaching the picker on an explicit leg means
    `_gait_cycle_possible` was false, which is `len(hsIps)` of 0 *or* 1. The
    one-heel-strike case does not reach the branch asserted here -- it falls
    through to `n_gait_cycles == 0` and raises a bare 'Not enough gait cycles
    found.', with no leg, no counts and no mention of manual entry. That is the
    same quiet drop this test exists to forbid, and it wants the
    `manualEventPicker is not None` branch the zero case already has. Widen
    this test when it gets one; do not widen the claim before then.
    """
    _gait_module, ui = pipeline
    seed = {}

    def never_opens(model):
        """A window that never opened still had the seed marked on it."""
        seed.update(model.picker.counts())

    with pytest.raises(Exception) as caught:
        _build(pipeline, session_dir, leg='r', allow_manual_entry=True,
               manual_event_provider=ui.make_manual_event_provider(
                   show=never_opens))

    # Stated rather than implied: both halves of this test's premise -- that
    # the seed was non-empty (so the emptiness backstop could not fire) and
    # that it carried no rHS (so the branch below is the one reached) -- are
    # facts about the trial, and a data change that alters either should
    # report itself here instead of surfacing as a confusing assertion below.
    assert seed == {'rHS': 0, 'rTO': 1, 'lHS': 1, 'lTO': 0}, (
        "the seed composition changed; this test pins the zero-rHS branch: %r"
        % (seed,))

    message = str(caught.value)
    assert "no heel-strike events" in message, (
        "an incomplete seed passed as a segmentable answer: " + message)
    assert "'rHS': 0" in message, (
        "the failure did not quote what the picker was actually holding: "
        + message)


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


# -- one trial, one window, on the real pipeline ---------------------------
#
# The wiring tests in test_gait_event_picker_wiring.py drive reuse_across_legs
# against a stub timeline. This drives it against the real one: the
# MarkerTimeline collect_manual_events actually builds, carrying the trial's
# own frame count and trial_name, on a trial whose automatic detection
# genuinely fails. run_gait_analysis constructs gait_analysis twice per trial
# -- leg='r' then leg='l' -- and this is the pair.


@pytest.fixture(scope="module")
def both_legs(pipeline, session_dir):
    """The same trial analysed on both legs, sharing one wrapped provider --
    exactly what run_gait_analysis does."""
    gait_module, ui = pipeline
    opened = []

    def scripted_operator(model):
        # Shifted on every call, so a replay is distinguishable from a second
        # visit to the window. An operator who happened to pick identically
        # twice would make a broken reuse look like a working one, which is
        # what an earlier version of this fixture did.
        motion = model.picker.motion
        opened.append((motion.name, motion.n_rows))
        shift = 0.01 * len(opened)
        for event_type, fraction in (
                ('rHS', 0.10), ('lTO', 0.16), ('lHS', 0.30), ('rTO', 0.36),
                ('rHS', 0.50), ('lTO', 0.56), ('lHS', 0.70), ('rTO', 0.76),
                ('rHS', 0.90)):
            model.select(event_type)
            model.pick_at(float(int(motion.n_rows * (fraction + shift))))

    provider = ui.reuse_across_legs(
        ui.make_manual_event_provider(show=scripted_operator))

    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        legs = [
            gait_module.gait_analysis(
                str(session_dir), TRIAL, 0.0, 0.0, leg=leg, n_gait_cycles=-1,
                allow_manual_entry=True, modelName=MODEL,
                manual_event_provider=provider)
            for leg in ('r', 'l')
        ]
    finally:
        os.chdir(cwd)
    return legs, opened


def test_one_trial_asks_the_operator_once_across_both_legs(both_legs):
    """Both legs of a trial fail auto-trim together, so an unwrapped provider
    would open two windows for one trial and accept two different answers."""
    _legs, opened = both_legs

    assert len(opened) == 1, (
        "the picker window opened %d times for one trial; the operator is "
        "being asked the same question about the same curves twice"
        % len(opened))
    assert opened[0][0] == TRIAL


def test_both_legs_are_segmented_from_the_same_picked_events(both_legs):
    """The replay has to reach the real picker, not merely skip the window --
    the second leg's events are what its gait cycles are built from."""
    legs, _opened = both_legs
    right, left = legs

    assert right.manualEventPicker is not None
    assert left.manualEventPicker is not None
    assert left.manualEventPicker.as_segment_walking_events() == \
        right.manualEventPicker.as_segment_walking_events(), (
            "the second leg was picked afresh rather than replayed, so one "
            "trial's two legs are segmented from two different event sets")


def test_the_replayed_leg_still_produces_gait_cycles(both_legs):
    """A replay that marked nothing would leave the second leg declining, and
    a decline raises rather than silently producing an empty result."""
    legs, _opened = both_legs
    _right, left = legs

    assert len(left.gaitEvents['ipsilateralIdx']) >= 1
