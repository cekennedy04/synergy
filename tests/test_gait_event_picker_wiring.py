"""The picker window, wired into a run that can actually reach it.

`gait_event_picker_ui.py` shipped complete and untested in production: nothing
in this repo passed `manual_event_provider`, so `segment_walking` always fell
through to the stdin frame-index prompt and the window never opened. These
tests pin the wiring itself -- which caller supplies a provider, which
deliberately does not, and what happens on the second of a trial's two legs.

**Why the second leg is the interesting case.** `run_gait_analysis` builds
`gait_analysis` twice per trial, `leg='r'` then `leg='l'`, because R8's
symmetry metric is only defined by comparing both. Each constructor runs
`segment_walking` on the same trial, so a trial auto-trim cannot segment fails
for both legs and a naive wiring opens the picker window twice for one trial,
asking the same operator the same question about the same curves. Worse, the
two answers can differ. `reuse_across_legs` is what makes one trial one
window.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DRIVER_PATH = REPO_ROOT / "Examples" / "gaitAnalysis-UCM.py"


def _load(name, relative_path):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def picker_mod():
    return _load("gait_event_picker_for_wiring", "gait_event_picker.py")


@pytest.fixture(scope="module")
def ui():
    return _load("gait_event_picker_ui_for_wiring", "gait_event_picker_ui.py")


@pytest.fixture(scope="module")
def driver():
    spec = importlib.util.spec_from_file_location(
        "gaitAnalysis_UCM_for_wiring", DRIVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Timeline:
    """The shape GaitEventPicker asks a motion for. Deliberately not the real
    MarkerTimeline: this file is about wiring, and the real one drags in
    gait_analysis_UCM_fixed's opensim import chain."""

    def __init__(self, name="Trial1", n_rows=60):
        self.name = name
        self.n_rows = n_rows
        self.signals = {}

    def time_at(self, row):
        return round(row * 0.016667, 6)


def _picker(picker_mod, name="Trial1", n_rows=60):
    return picker_mod.GaitEventPicker(_Timeline(name, n_rows))


def _one_cycle(picker):
    for event, row in (("rHS", 2), ("lTO", 8), ("lHS", 15), ("rTO", 22),
                       ("rHS", 30)):
        picker.mark(event, row)
    return picker


# -- one trial, one window -------------------------------------------------


def test_the_second_leg_replays_the_first_legs_picks(ui, picker_mod):
    """The operator answers once. The second `gait_analysis` of the same trial
    gets the same events without a window."""
    opened = []

    def inner(picker):
        opened.append(picker.motion.name)
        _one_cycle(picker)

    provider = ui.reuse_across_legs(inner)

    right = _picker(picker_mod)
    provider(right)
    left = _picker(picker_mod)
    provider(left)

    assert opened == ["Trial1"], "the window opened twice for one trial"
    assert left.as_segment_walking_events() == right.as_segment_walking_events()


def test_a_decline_is_remembered_too(ui, picker_mod):
    """Cancel means "use auto-trim". Asking again on the other leg would
    re-open the window the operator just dismissed."""
    opened = []

    def inner(picker):
        opened.append(picker.motion.name)          # picks nothing: a decline

    provider = ui.reuse_across_legs(inner)

    provider(_picker(picker_mod))
    left = _picker(picker_mod)
    provider(left)

    assert opened == ["Trial1"]
    assert left.as_segment_walking_events() == ([], [], [], [])


def test_a_different_trial_opens_its_own_window(ui, picker_mod):
    """Remembering is per trial, not per session. Replaying Trial1's frames
    onto Trial2 would land events on frames nobody chose."""
    opened = []

    def inner(picker):
        opened.append(picker.motion.name)
        _one_cycle(picker)

    provider = ui.reuse_across_legs(inner)

    provider(_picker(picker_mod, name="Trial1"))
    provider(_picker(picker_mod, name="Trial2"))

    assert opened == ["Trial1", "Trial2"]


def test_an_unnamed_trial_is_never_remembered(ui, picker_mod):
    """Frame count is not identity -- fixed-duration walk captures from one
    participant routinely share one. With no name to tell two trials apart,
    the safe answer is to ask again, which is `collect_manual_events`' own
    reasoning about the same ambiguity."""
    opened = []

    def inner(picker):
        opened.append(picker.motion.n_rows)
        _one_cycle(picker)

    provider = ui.reuse_across_legs(inner)

    provider(_picker(picker_mod, name=""))
    provider(_picker(picker_mod, name=""))

    assert opened == [60, 60]


def test_a_same_name_trial_of_a_different_length_is_not_replayed(ui,
                                                                 picker_mod):
    """Trimming changes the frame count. Replaying rows across two different
    index spaces is exactly what `from_dict` refuses, so do not manufacture
    the situation here."""
    opened = []

    def inner(picker):
        opened.append(picker.motion.n_rows)
        _one_cycle(picker)

    provider = ui.reuse_across_legs(inner)

    provider(_picker(picker_mod, n_rows=60))
    provider(_picker(picker_mod, n_rows=48))

    assert opened == [60, 48]


def test_a_provider_that_returns_its_own_picker_is_remembered(ui, picker_mod):
    """`collect_manual_events` accepts a returned picker as well as None -- a
    set restored from disk, say -- so the memory has to read that shape too."""
    def inner(picker):
        return _one_cycle(_picker(picker_mod))

    provider = ui.reuse_across_legs(inner)

    first = provider(_picker(picker_mod))
    left = _picker(picker_mod)
    second = provider(left)

    assert first is not None
    assert second is None, "a replay marks the picker it was handed"
    assert left.as_segment_walking_events() == \
        first.as_segment_walking_events()


def test_the_replay_reaches_every_event_type(ui, picker_mod):
    """rHS, lHS, rTO, lTO -- the contract edit #13 was about, across the
    replay boundary as well as across the picker's own return."""
    provider = ui.reuse_across_legs(lambda picker: _one_cycle(picker))

    provider(_picker(picker_mod))
    left = _picker(picker_mod)
    provider(left)

    assert left.as_segment_walking_events() == \
        ([2, 30], [15], [22], [8])


# -- which callers supply one ----------------------------------------------


class _FakeAnalysis:
    """Stands in for gait_analysis. Records the keywords it was constructed
    with; every attribute the driver reads afterwards is a stub."""

    seen = []

    def __init__(self, *args, **kwargs):
        type(self).seen.append(kwargs)

    def get_center_of_mass_values(self, **_kwargs):
        return {}

    def compute_scalars(self, _names):
        return {}

    def get_coordinates_normalized_time(self):
        return {}


@pytest.fixture
def fake_pipeline(driver, monkeypatch):
    """Runs `run_gait_analysis` without opensim, and hands back the keywords
    each of the two `gait_analysis` constructions received."""
    import types

    _FakeAnalysis.seen = []
    module = types.ModuleType("gait_analysis_UCM_fixed")
    module.gait_analysis = _FakeAnalysis
    monkeypatch.setitem(sys.modules, "gait_analysis_UCM_fixed", module)
    monkeypatch.setattr(driver, "compute_foot_progression_angles",
                        lambda *_a, **_k: ([], []))
    return _FakeAnalysis.seen


def test_run_gait_analysis_hands_the_provider_to_both_legs(driver,
                                                            fake_pipeline):
    """Both legs, or the second one silently drops back to the stdin prompt
    the window was supposed to replace."""
    sentinel = object()

    driver.run_gait_analysis("session", "Trial1",
                             manual_event_provider=sentinel)

    assert len(fake_pipeline) == 2
    assert [kwargs["leg"] for kwargs in fake_pipeline] == ["r", "l"]
    assert all(kwargs["manual_event_provider"] is sentinel
               for kwargs in fake_pipeline)


def test_run_gait_analysis_defaults_to_no_provider(driver, fake_pipeline):
    """The default has to stay None: `run_batch` reaches this function too,
    and a batch run that opens a window is a batch run that hangs."""
    driver.run_gait_analysis("session", "Trial1")

    assert all(kwargs["manual_event_provider"] is None
               for kwargs in fake_pipeline)


def test_process_trial_threads_the_provider_through(driver, monkeypatch):
    """`process_trial` is the only path from either entry point to
    `run_gait_analysis`, so a provider it drops never arrives."""
    import types

    seen = {}
    monkeypatch.setitem(sys.modules, "utils", types.SimpleNamespace(
        download_trial=lambda *_a, **_k: "Trial1",
        get_trial_id=lambda *_a, **_k: "id"))
    monkeypatch.setattr(driver, "resolve_data_folder", lambda: Path("."))
    monkeypatch.setattr(driver, "print_scalar_results", lambda _r: None)
    monkeypatch.setattr(driver, "export_individual_curves_csv",
                        lambda *_a, **_k: ("r.csv", "l.csv"))

    def fake_run(base, trial, **kwargs):
        seen.update(kwargs)
        return {}
    monkeypatch.setattr(driver, "run_gait_analysis", fake_run)

    sentinel = object()
    driver.process_trial("base", "Trial1", "session", "subject", "save",
                         manual_event_provider=sentinel)

    assert seen["manual_event_provider"] is sentinel


def test_a_batch_run_never_supplies_a_provider(driver):
    """The batch path passes allow_manual_entry=False and must not acquire a
    window by another route. Read from the source: driving `run_batch` needs
    a real session on disk."""
    source = DRIVER_PATH.read_text(encoding="utf-8")
    batch = source[source.index("def run_batch("):source.index("def run_interactive(")]

    assert "manual_event_provider" not in batch, (
        "run_batch acquired a manual_event_provider; an unattended run that "
        "opens a picker window blocks forever on a human who is not there.")


def test_the_interactive_run_supplies_a_reusing_provider(driver):
    """The interactive menu is the one caller that should get the window: it
    already stops and prompts on stdin today, so this replaces a prompt rather
    than introducing an interruption."""
    source = DRIVER_PATH.read_text(encoding="utf-8")
    interactive = source[source.index("def run_interactive("):source.index("def main(")]

    assert "make_manual_event_provider" in interactive
    assert "reuse_across_legs" in interactive, (
        "the interactive path builds a raw provider, so a trial's two legs "
        "would each open their own picker window.")


def test_a_misbehaving_provider_keeps_its_own_diagnostic(ui, picker_mod):
    """`collect_manual_events` has the message for a provider that returns the
    wrong shape. The memory must not die on a missing attribute first and bury
    it -- so it declines to remember and passes the value straight through."""
    provider = ui.reuse_across_legs(lambda _picker: "not a picker")

    assert provider(_picker(picker_mod)) == "not a picker"
