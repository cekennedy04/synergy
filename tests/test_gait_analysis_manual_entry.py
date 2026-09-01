"""Tests for manual gait-event entry in gait_analysis_UCM_fixed.py (Phase 2.3).

`manual_steps` is the third rung of segment_walking's fallback chain, after
prominence escalation and the auto-trim retry loop. It used to be four stdin
prompts for event TIMES nested inside segment_walking -- unreachable by a test
and unusable from a GUI. It is now a module-level function driving
gait_event_picker.GaitEventPicker, whose events are frame indices.

Three things are worth pinning here, in descending order of how expensive they
are to get wrong:

1. **The return order.** segment_walking unpacks `rHS, lHS, rTO, lTO`. Edit #13
   exists because trimend returned those four in a different order for months,
   putting left heel-strikes in the right toe-off slot and silently corrupting
   every downstream metric. Both a behavioural test and an AST test cover it.
2. **Batch runs cannot block.** clinician_gui.run_batch and
   process_participants.py pass allow_manual_entry=False and run unattended.
   A prompt reached from there is a hung job nobody is watching.
3. **Frames, not times.** The stdin fallback accepts row indices, because a
   time typed back in does not land on the frame the operator saw.

The real gait_analysis needs OpenSim, which this environment does not have, so
utilsKinematics is stubbed for the module load. Nothing under test touches the
base class: manual_steps has always taken `self` explicitly, so a plain object
carrying markerDict and the manual-entry flags drives it exactly as the real
instance does.
"""
import ast
import builtins
import importlib.util
import re
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PATH = REPO_ROOT / "gait_analysis_UCM_fixed.py"

MODULE_NAME = "gait_analysis_UCM_fixed_manual_entry_under_test"


def _load_gait_analysis_module():
    """Load the real module with utilsKinematics stubbed out.

    The stub is removed from sys.modules again afterwards: `kinematics` is only
    needed while the class statement executes, and leaving a fake in place
    would change what any later test in the same session imports.
    """
    stub = types.ModuleType("utilsKinematics")

    class kinematics:  # noqa: N801 - mirrors the real lowercase class name
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "the stubbed kinematics base class was instantiated; these "
                "tests drive manual_steps directly and must never construct a "
                "real gait_analysis")

    stub.kinematics = kinematics

    previous = sys.modules.get("utilsKinematics")
    sys.modules["utilsKinematics"] = stub
    try:
        spec = importlib.util.spec_from_file_location(MODULE_NAME, SOURCE_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = module
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            del sys.modules["utilsKinematics"]
        else:
            sys.modules["utilsKinematics"] = previous
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_gait_analysis_module()


@pytest.fixture(scope="module")
def source():
    return SOURCE_PATH.read_text(encoding="utf-8", errors="ignore")


# The real dt from a .mot this pipeline produced: 0.016667, 0.017, 0.016,
# 0.017. Non-uniform on purpose -- it is the whole reason events are stored as
# frame indices rather than times.
_INTERVALS = [0.016667, 0.017, 0.016, 0.017]


def _trial_times(n_frames=40):
    times, now = [0.0], 0.0
    for index in range(n_frames - 1):
        now = round(now + _INTERVALS[index % len(_INTERVALS)], 6)
        times.append(now)
    return times


class FakeAnalysis:
    """The surface of gait_analysis that manual_steps actually touches."""

    def __init__(self, n_frames=40, allow_manual_entry=True, provider=None):
        self.markerDict = {"time": _trial_times(n_frames)}
        self.allow_manual_entry = allow_manual_entry
        self.manual_event_provider = provider
        self.trial_name = "Trial3_1"
        self.dflag = 0
        self.rhs, self.lhs, self.rto, self.lto = [], [], [], []


def _provider_marking(**events):
    """A stand-in UI: marks the given rows on the picker it is handed."""
    calls = []

    def provider(picker):
        calls.append(picker)
        for event_type, rows in events.items():
            for row in rows:
                picker.mark(event_type, row)
        return None

    provider.calls = calls
    return provider


# -- 1. the return contract edit #13 was about ------------------------------


def test_manual_steps_returns_events_in_segment_walkings_unpacking_order(mod):
    """segment_walking does `rHS,lHS,rTO,lTO = manual_steps(self)`. If these
    four come back in any other order, left heel-strikes land in the right
    toe-off slot and every downstream metric is plausibly wrong."""
    analysis = FakeAnalysis(
        provider=_provider_marking(rHS=[1], lHS=[2], rTO=[3], lTO=[4]))

    rHS, lHS, rTO, lTO = mod.manual_steps(analysis)

    assert rHS == [1]
    assert lHS == [2]
    assert rTO == [3]
    assert lTO == [4]


def test_manual_steps_returns_exactly_four_values(mod):
    analysis = FakeAnalysis(
        provider=_provider_marking(rHS=[1], lHS=[2], rTO=[3], lTO=[4]))

    assert len(mod.manual_steps(analysis)) == 4


def test_every_gait_event_return_in_the_module_uses_the_same_order(source):
    """detect_gait_peaks, trimend and manual_steps are three suppliers of the
    same four-tuple. Read out of the AST rather than by regex so a reordered
    or lengthened return cannot slip past on formatting."""
    tree = ast.parse(source)
    names = {"rHS", "lHS", "rTO", "lTO"}

    returns = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Tuple):
            continue
        elements = node.value.elts
        if not all(isinstance(element, ast.Name) for element in elements):
            continue
        returned = [element.id for element in elements]
        if names & set(returned):
            returns.append(returned)

    assert returns, "no gait-event return statements found; the pin is dead"
    for returned in returns:
        assert returned == ["rHS", "lHS", "rTO", "lTO"], (
            "a gait-event return was reordered or given a fifth value: "
            + str(returned))


def test_segment_walking_still_unpacks_manual_steps_into_those_names(source):
    """The other half of the contract: the call site's names must line up with
    the return, which is exactly what edit #13 found broken."""
    assert re.search(
        r"rHS\s*,\s*lHS\s*,\s*rTO\s*,\s*lTO\s*=\s*manual_steps\(self\)", source)


# -- 2. unattended batch runs cannot block ---------------------------------


def test_manual_entry_disabled_raises_instead_of_prompting(mod, monkeypatch):
    """clinician_gui.run_batch and process_participants.py depend on this. The
    input patch makes a prompt a visibly different failure from the refusal,
    so the test proves stdin was never touched rather than assuming it."""
    monkeypatch.setattr(
        builtins, "input",
        lambda *args: pytest.fail("manual entry prompted with it disabled"))
    analysis = FakeAnalysis(allow_manual_entry=False)

    with pytest.raises(Exception, match="allow_manual_entry=False"):
        mod.manual_steps(analysis)


def test_manual_entry_disabled_wins_over_a_wired_up_provider(mod):
    """A provider left on the object does not re-enable manual entry: the
    batch flag is the authority, so a GUI-configured object reused in a batch
    run still refuses."""
    provider = _provider_marking(rHS=[1])
    analysis = FakeAnalysis(allow_manual_entry=False, provider=provider)

    with pytest.raises(Exception, match="allow_manual_entry=False"):
        mod.manual_steps(analysis)
    assert provider.calls == []


def test_the_only_stdin_prompt_left_in_the_module_is_guarded(source):
    """segment_walking's "enter events manually? [Y/N]" is the module's one
    remaining bare input(). Both escape hatches -- the batch flag and a wired
    up provider -- must be checked before it, or an unattended run or a GUI
    session blocks on a terminal nobody is reading."""
    calls = [node for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "input"]

    assert len(calls) == 1, (
        "expected exactly one bare input() call; manual entry's own prompt "
        "takes an injectable input_fn")

    prompt_line = calls[0].lineno
    batch_guard = source.index("if not self.allow_manual_entry:\n"
                               "                        trimflag=1")
    provider_guard = source.index(
        "if getattr(self, 'manual_event_provider', None) is not None:")
    prompt_offset = source.index('input("Do you want to enter gait events')

    assert source[:batch_guard].count("\n") < prompt_line
    assert batch_guard < prompt_offset
    assert provider_guard < prompt_offset


# -- 3. the picker drives manual entry -------------------------------------


def test_the_provider_is_handed_a_picker_over_this_trials_frames(mod):
    provider = _provider_marking(rHS=[0])
    analysis = FakeAnalysis(n_frames=40, provider=provider)

    mod.manual_steps(analysis)

    picker, = provider.calls
    assert picker.motion.n_rows == 40
    assert picker.motion.name == "Trial3_1"


def test_a_provider_may_return_its_own_picker(mod):
    """A set restored from disk, for instance -- the provider is not required
    to mark on the picker it was handed."""
    def provider(picker):
        replacement = type(picker)(picker.motion)
        replacement.mark("lHS", 7)
        return replacement

    rHS, lHS, rTO, lTO = mod.manual_steps(FakeAnalysis(provider=provider))

    assert lHS == [7]
    assert (rHS, rTO, lTO) == ([], [], [])


def test_a_provider_returning_something_that_is_not_a_picker_is_refused(mod):
    """Returning the four-tuple directly is the obvious wiring mistake, and it
    would otherwise reach segmentation as an object nobody can unpack."""
    analysis = FakeAnalysis(provider=lambda picker: ([1], [2], [3], [4]))

    with pytest.raises(TypeError, match="as_segment_walking_events"):
        mod.manual_steps(analysis)


def test_a_picker_built_over_a_different_trial_is_refused(mod, monkeypatch):
    """Events are frame indices. Applied to another trial they name frames
    nobody chose -- silently, which is the failure mode this file keeps
    finding."""
    def provider(picker):
        other = mod.MarkerTimeline(_trial_times(12), name="some other trial")
        return type(picker)(other)

    with pytest.raises(ValueError, match="do not transfer between trials"):
        mod.manual_steps(FakeAnalysis(n_frames=40, provider=provider))


def test_the_picked_events_are_cached_for_the_second_leg(mod):
    """segment_walking may run again on the same instance; dflag exists so the
    operator is not asked twice for the same trial."""
    provider = _provider_marking(rHS=[1], lHS=[2], rTO=[3], lTO=[4])
    analysis = FakeAnalysis(provider=provider)

    first = mod.manual_steps(analysis)
    second = mod.manual_steps(analysis)

    assert first == second
    assert len(provider.calls) == 1


def test_the_picker_is_kept_on_the_analysis_for_inspection(mod):
    analysis = FakeAnalysis(provider=_provider_marking(rHS=[1]))

    mod.manual_steps(analysis)

    assert analysis.manualEventPicker.rows("rHS") == [1]


# -- ordering is reported, never enforced ----------------------------------


def test_an_out_of_order_set_is_warned_about_but_still_returned(mod, capsys):
    """A pathological gait may genuinely violate the expected cycle, and this
    project stopped hard-refusing trials on 2026-08-27."""
    analysis = FakeAnalysis(provider=_provider_marking(rHS=[0], rTO=[3]))

    rHS, lHS, rTO, lTO = mod.manual_steps(analysis)

    assert rHS == [0] and rTO == [3]
    assert "ordering warning" in capsys.readouterr().out


def test_a_correct_cycle_is_reported_without_a_warning(mod, capsys):
    provider = _provider_marking(rHS=[0, 20], lTO=[3], lHS=[8], rTO=[12])
    analysis = FakeAnalysis(provider=provider)

    mod.manual_steps(analysis)

    out = capsys.readouterr().out
    assert "correct gait order" in out
    assert "ordering warning" not in out


# -- frames, not times -----------------------------------------------------


def test_the_stdin_fallback_takes_frame_indices_verbatim(mod):
    """No snapping, no nearest-sample search: what is typed is the frame that
    is stored. The old prompt took times and ran argmin over markerDict, which
    on this trial's non-uniform dt could land a frame off."""
    picker = mod.build_manual_picker(FakeAnalysis(n_frames=40))
    answers = iter(["0, 20", "12", "8", "3"])

    mod.prompt_for_event_rows(picker, input_fn=lambda prompt: next(answers),
                              output_fn=lambda *args: None)

    assert picker.as_segment_walking_events() == ([0, 20], [8], [12], [3])


def test_the_stdin_fallback_refuses_something_that_looks_like_a_time(mod):
    picker = mod.build_manual_picker(FakeAnalysis(n_frames=40))
    answers = iter(["0.2833"])

    with pytest.raises(ValueError, match="does not accept times"):
        mod.prompt_for_event_rows(picker, input_fn=lambda prompt: next(answers),
                                  output_fn=lambda *args: None)


def test_the_stdin_fallback_accepts_a_blank_line_as_no_events(mod):
    picker = mod.build_manual_picker(FakeAnalysis(n_frames=40))
    answers = iter(["1", "", "  ", ""])

    mod.prompt_for_event_rows(picker, input_fn=lambda prompt: next(answers),
                              output_fn=lambda *args: None)

    assert picker.as_segment_walking_events() == ([1], [], [], [])


def test_manual_steps_falls_back_to_stdin_when_no_ui_is_wired_up(mod, monkeypatch):
    answers = iter(["1", "3", "2", "4"])
    monkeypatch.setattr(builtins, "input", lambda prompt: next(answers))
    analysis = FakeAnalysis(provider=None)

    rHS, lHS, rTO, lTO = mod.manual_steps(analysis)

    assert (rHS, lHS, rTO, lTO) == ([1], [2], [3], [4])


def test_a_frame_outside_the_trial_is_refused_by_the_fallback(mod):
    picker = mod.build_manual_picker(FakeAnalysis(n_frames=40))
    answers = iter(["40"])

    with pytest.raises(IndexError):
        mod.prompt_for_event_rows(picker, input_fn=lambda prompt: next(answers),
                                  output_fn=lambda *args: None)


# -- the timeline the picker sits on ---------------------------------------


def test_the_timeline_reads_the_trials_own_sample_times(mod):
    """Never reconstructed as start + row*dt: this trial's dt alternates
    0.016667, 0.017, 0.016, 0.017, so the arithmetic drifts against the file."""
    times = _trial_times(40)
    timeline = mod.MarkerTimeline(times)

    assert timeline.n_rows == 40
    assert timeline.time_at(5) == times[5]
    assert timeline.time_at(39) == times[39]


def test_the_timeline_refuses_a_row_it_does_not_have(mod):
    timeline = mod.MarkerTimeline(_trial_times(10))

    with pytest.raises(IndexError):
        timeline.time_at(10)


def test_the_timeline_accepts_the_numpy_array_markerdict_actually_holds(mod):
    numpy = pytest.importorskip("numpy")
    timeline = mod.MarkerTimeline(numpy.array(_trial_times(10)))

    assert timeline.n_rows == 10
    assert timeline.time_at(3) == pytest.approx(_trial_times(10)[3])


def test_build_manual_picker_starts_empty_over_the_whole_trial(mod):
    picker = mod.build_manual_picker(FakeAnalysis(n_frames=25))

    assert picker.motion.n_rows == 25
    assert picker.as_segment_walking_events() == ([], [], [], [])
