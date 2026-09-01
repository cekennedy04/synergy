"""Drive the manual picker against REAL marker data from Data/.

Everything else covering the picker runs on fixtures. This runs on the actual
`.trc` files in the repo -- real frame counts, real sample times, real
detection signals -- because a picker that works on a 40-frame fixture and not
on a 969-frame trial is not validated.

`gait_analysis.__init__` still cannot run here: `utils.py` authenticates
against the OpenCap API at import time and blocks on `getpass` when there is
no `.env`. The picker never needed any of that. What it needs comes from the
`.trc`, which `utilsTRC` reads without OpenSim or the API, so the parts under
test are reachable and the parts that are not are honestly out of scope --
this does not exercise `segment_walking` end to end.

Skips rather than fails when `Data/` is absent, so a fresh clone without the
(gitignored) session data still gets a green suite.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "Data"

# The eight markers segment_walking projects to build its detection signals.
MARKERS_NEEDED = ('r_calc_study', 'L_calc_study', 'r_toe_study', 'L_toe_study',
                  'r.PSIS_study', 'L.PSIS_study', 'r.ASIS_study', 'L.ASIS_study')

# Below this a capture is a static/neutral pose, not a walk. Real walking
# trials in Data/ run 400-1000 frames at 60Hz; the shortest thing in there is
# 36 frames.
MIN_GAIT_FRAMES = 300


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gait_module():
    stub = types.ModuleType("utilsKinematics")
    stub.kinematics = type("kinematics", (), {})
    previous = sys.modules.get("utilsKinematics")
    sys.modules["utilsKinematics"] = stub
    try:
        return _load("gait_analysis_for_real_data_tests",
                     "gait_analysis_UCM_fixed.py")
    finally:
        if previous is None:
            del sys.modules["utilsKinematics"]
        else:
            sys.modules["utilsKinematics"] = previous


@pytest.fixture(scope="module")
def picker_module():
    return _load("gait_event_picker_for_real_data_tests", "gait_event_picker.py")


@pytest.fixture(scope="module")
def ui(gait_module):
    return _load("gait_event_picker_ui_for_real_data_tests",
                 "gait_event_picker_ui.py")


@pytest.fixture(scope="module")
def real_trial():
    """One real trial: (name, times, signals), computed exactly as
    segment_walking computes them."""
    if not DATA_ROOT.is_dir():
        pytest.skip("Data/ is gitignored and absent in this checkout")
    numpy = pytest.importorskip("numpy")
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from utilsTRC import trc_2_dict
    except Exception as exc:                       # pragma: no cover
        pytest.skip("utilsTRC unavailable: %s" % exc)

    for session in sorted(DATA_ROOT.glob("OpenCapData_*")):
        for trc in sorted((session / "MarkerData").glob("*.trc")):
            data = trc_2_dict(str(trc))
            markers = data['markers']
            if any(name not in markers for name in MARKERS_NEEDED):
                continue
            # Sessions carry short static/neutral captures alongside the walks
            # -- the first trial alphabetically in Data/ is 36 frames. Picking
            # one of those would make every assertion below vacuous, which is
            # what MIN_GAIT_FRAMES below is guarding.
            if len(data['time']) < MIN_GAIT_FRAMES:
                continue

            # Verbatim from segment_walking.
            r_calc_rel = markers['r_calc_study'] - markers['r.PSIS_study']
            r_toe_rel = markers['r_toe_study'] - markers['r.PSIS_study']
            l_calc_rel = markers['L_calc_study'] - markers['L.PSIS_study']
            l_toe_rel = markers['L_toe_study'] - markers['L.PSIS_study']
            mid_psis = (markers['r.PSIS_study'] + markers['L.PSIS_study']) / 2
            mid_asis = (markers['r.ASIS_study'] + markers['L.ASIS_study']) / 2
            mid_dir = mid_asis - mid_psis
            floor = numpy.copy(mid_dir)
            floor[:, 1] = 0
            floor = floor / numpy.linalg.norm(floor, axis=1, keepdims=True)
            signals = {
                'r_calc': numpy.einsum('ij,ij->i', floor, r_calc_rel),
                'l_calc': numpy.einsum('ij,ij->i', floor, l_calc_rel),
                'r_toe': numpy.einsum('ij,ij->i', floor, r_toe_rel),
                'l_toe': numpy.einsum('ij,ij->i', floor, l_toe_rel),
            }
            return trc.stem, list(data['time']), signals
    pytest.skip("no walking trial in Data/ carries the markers segment_walking "
                "needs")


@pytest.fixture
def real_model(gait_module, picker_module, ui, real_trial):
    name, times, signals = real_trial
    timeline = gait_module.MarkerTimeline(times, name=name, signals=signals)
    return ui.EventPickerModel(picker_module.GaitEventPicker(timeline))


def test_the_trial_is_big_enough_to_be_worth_testing_on(real_model):
    """Guards the fixture: a 40-frame fixture masquerading as real data would
    make every assertion below meaningless."""
    assert real_model.picker.motion.n_rows >= MIN_GAIT_FRAMES


def test_every_frame_reads_its_own_time_from_the_real_file(real_model,
                                                           real_trial):
    _name, times, _signals = real_trial
    motion = real_model.picker.motion

    mismatched = [row for row in range(motion.n_rows)
                  if motion.time_at(row) != float(times[row])]

    assert mismatched == []


def test_clicks_land_on_the_intended_frames_across_a_real_trial(real_model):
    """Sampled across the whole trial, not just the start, and off-centre --
    an operator's click never lands exactly on a frame boundary."""
    n_rows = real_model.picker.motion.n_rows
    intended = [int(n_rows * fraction)
                for fraction in (0.05, 0.25, 0.5, 0.75, 0.95)]

    for frame in intended:
        assert real_model.frame_for(frame + 0.4) == frame
        assert real_model.frame_for(frame - 0.4) == frame


def test_the_contract_order_holds_on_a_real_trial(real_model):
    """rHS, lHS, rTO, lTO -- the order edit #13 was about, on real frames."""
    n_rows = real_model.picker.motion.n_rows
    marks = {'rHS': int(n_rows * 0.10), 'lTO': int(n_rows * 0.30),
             'lHS': int(n_rows * 0.50), 'rTO': int(n_rows * 0.70)}
    for event_type, frame in marks.items():
        real_model.select(event_type)
        real_model.pick_at(float(frame))

    rHS, lHS, rTO, lTO = real_model.picker.as_segment_walking_events()

    assert rHS == [marks['rHS']]
    assert lHS == [marks['lHS']]
    assert rTO == [marks['rTO']]
    assert lTO == [marks['lTO']]


def test_a_real_cycle_reports_correct_ordering(real_model):
    n_rows = real_model.picker.motion.n_rows
    for event_type, fraction in (('rHS', 0.10), ('lTO', 0.30), ('lHS', 0.50),
                                 ('rTO', 0.70), ('rHS', 0.90)):
        real_model.select(event_type)
        real_model.pick_at(float(int(n_rows * fraction)))

    ok, message = real_model.verdict()

    assert ok is True, message


def test_the_frame_reference_stays_readable_on_a_real_trial(gait_module,
                                                            real_model):
    motion = real_model.picker.motion

    lines = gait_module.frame_time_reference(motion)

    assert len(lines) <= 21, "a several-hundred-frame trial flooded the prompt"
    assert str(motion.n_rows - 1) in lines[-1]


def test_events_are_drawn_against_the_real_detection_signals(real_model):
    """Heel strikes on the calc trace, toe-offs on the toe trace -- the same
    curves detect_gait_peaks ran find_peaks over."""
    motion = real_model.picker.motion
    frame = int(motion.n_rows * 0.4)
    real_model.select('rHS')
    real_model.pick_at(float(frame))

    frames, values = real_model.events_for('rHS')

    assert frames == [frame]
    assert values == [motion.signals['r_calc'][frame]]


def test_the_window_renders_the_real_trial_offscreen(ui, real_model,
                                                     monkeypatch):
    """Catches plotting errors that only a real trial's shape would trigger.

    The interactive-backend guard is stubbed to render under Agg at all --
    which is precisely what that guard exists to stop a real operator doing."""
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    monkeypatch.setattr(ui, "assert_interactive_backend", lambda: None)
    real_show, plt.show = plt.show, lambda *args, **kwargs: None
    try:
        artists = ui.show_picker_window(real_model)
        figure = plt.gcf()
        panels = [axis for axis in figure.axes if axis.get_title(loc='left')]

        assert len(artists) == 4
        assert len(panels) == 2, "expected a right-leg and a left-leg panel"
        assert sum(len(axis.lines) for axis in panels) == 8, \
            "expected 4 signal traces and 4 event markers"
    finally:
        plt.show = real_show
        plt.close('all')


def test_cancelling_a_real_trial_hands_back_a_decline(real_model):
    """An empty set is how segment_walking learns to fall back to auto-trim."""
    real_model.pick_at(float(int(real_model.picker.motion.n_rows * 0.3)))

    real_model.cancel()

    assert real_model.picker.as_segment_walking_events() == ([], [], [], [])
