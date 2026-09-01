"""Tests for gait_event_picker_ui.py.

No display and no matplotlib: every decision the picker window makes lives in
EventPickerModel, and the window itself is a thin wiring layer over it. That
split is the only reason this is testable on the machines that run this suite.

What matters here, in order:

1. **Clicks map to frames, never through time.** The x axis IS the frame
   index. The picker stores frames and segment_walking consumes frames, so
   putting seconds in between would add a conversion that can only lose.
   (Not because these files are irregularly sampled: measured 2026-09-01, all
   77 .trc files in Data/ have a single dt of 0.016667.)
2. **Cancel actually empties the picker.** segment_walking reads an empty set
   as a decline and falls back to the auto-trim rung; a cancel that merely
   closed the window would hand back whatever was picked so far and skip
   rung two.
3. **Ordering is reported, never enforced** -- an out-of-order set is still
   handed back.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gait_module():
    """gait_analysis_UCM_fixed, loaded with utilsKinematics stubbed -- only
    MarkerTimeline is needed, and the real base class wants OpenSim."""
    import types

    stub = types.ModuleType("utilsKinematics")

    class kinematics:  # noqa: N801 - mirrors the real lowercase class name
        pass

    stub.kinematics = kinematics
    previous = sys.modules.get("utilsKinematics")
    sys.modules["utilsKinematics"] = stub
    try:
        return _load("gait_analysis_for_ui_tests", "gait_analysis_UCM_fixed.py")
    finally:
        if previous is None:
            del sys.modules["utilsKinematics"]
        else:
            sys.modules["utilsKinematics"] = previous


@pytest.fixture(scope="module")
def ui(gait_module):
    return _load("gait_event_picker_ui_under_test", "gait_event_picker_ui.py")


@pytest.fixture(scope="module")
def picker_module():
    return _load("gait_event_picker_for_ui_tests", "gait_event_picker.py")


_INTERVALS = [0.016667, 0.017, 0.016, 0.017]


def _times(n_frames=40):
    times, now = [0.0], 0.0
    for index in range(n_frames - 1):
        now = round(now + _INTERVALS[index % len(_INTERVALS)], 6)
        times.append(now)
    return times


@pytest.fixture
def picker(gait_module, picker_module):
    """A picker over a 40-frame trial carrying the four detector signals."""
    signals = {name: [float(i) * scale for i in range(40)]
               for scale, name in ((1.0, "r_calc"), (2.0, "r_toe"),
                                   (3.0, "l_calc"), (4.0, "l_toe"))}
    timeline = gait_module.MarkerTimeline(_times(40), name="Trial3_1",
                                          signals=signals)
    return picker_module.GaitEventPicker(timeline)


@pytest.fixture
def model(ui, picker):
    return ui.EventPickerModel(picker)


# -- clicks map to frames, never through time ------------------------------


def test_a_click_maps_to_the_nearest_frame(ui, model):
    """The axis is the frame index, so this is a round, not a conversion."""
    assert model.frame_for(11.4) == 11
    assert model.frame_for(11.6) == 12


def test_a_click_past_the_end_clamps_rather_than_refusing(model):
    """Aiming at the first or last frame and overshooting is not an error."""
    assert model.frame_for(-3.0) == 0
    assert model.frame_for(999.0) == 39


def test_picking_records_the_frame_under_the_click(model):
    frame = model.pick_at(11.6)

    assert frame == 12
    assert model.picker.rows("rHS") == [12]


def test_picking_uses_the_selected_event_type(model):
    model.select("lTO")
    model.pick_at(7.0)

    assert model.picker.rows("lTO") == [7]
    assert model.picker.rows("rHS") == []


def test_an_unknown_event_type_cannot_be_selected(ui, model):
    with pytest.raises(ValueError, match="unknown event type"):
        model.select("rHeelStrike")


def test_the_readout_reads_time_from_the_trial(model, picker):
    """Shown for orientation only -- time is never an input on this path."""
    text = model.readout(4.0)

    assert "frame 4" in text
    assert f"{picker.motion.time_at(4):.3f}" in text


# -- erasing ---------------------------------------------------------------


def test_right_clicking_near_an_event_erases_it(model):
    model.pick_at(12.0)

    removed = model.erase_at(13.0)

    assert removed == (12, "rHS")
    assert model.picker.rows("rHS") == []


def test_erasing_removes_any_type_not_just_the_selected_one(model):
    """An operator who spots a stray marker should not have to work out which
    button made it first."""
    model.select("lTO")
    model.pick_at(20.0)
    model.select("rHS")

    removed = model.erase_at(20.0)

    assert removed == (20, "lTO")


def test_erasing_far_from_anything_does_nothing(model):
    model.pick_at(2.0)

    assert model.erase_at(30.0) is None
    assert model.picker.rows("rHS") == [2]


def test_erasing_an_empty_set_is_not_an_error(model):
    assert model.erase_at(5.0) is None


# -- cancel is a decline, and must reach segment_walking as one ------------


def test_cancel_empties_the_picker(model):
    """segment_walking reads an empty set as a decline and falls back to
    auto-trim. A cancel that merely closed the window would hand back a
    half-picked set and skip rung two."""
    model.pick_at(1.0)
    model.select("lHS")
    model.pick_at(5.0)

    model.cancel()

    assert model.picker.as_segment_walking_events() == ([], [], [], [])
    assert model.cancelled is True


# -- the provider seam -----------------------------------------------------


def test_the_provider_returns_none_having_marked_the_picker(ui, picker):
    """The contract collect_manual_events expects."""
    def fake_window(model):
        model.select("rHS")
        model.pick_at(3.0)

    provider = ui.make_manual_event_provider(show=fake_window)

    assert provider(picker) is None
    assert picker.rows("rHS") == [3]


def test_the_provider_drives_the_picker_it_is_handed(ui, picker):
    """Not one of its own -- the frames must belong to this trial."""
    seen = []

    def fake_window(model):
        seen.append(model.picker)
        model.pick_at(1.0)      # a window that picks nothing now raises

    provider = ui.make_manual_event_provider(show=fake_window)

    provider(picker)

    assert seen == [picker]


def test_a_cancelled_provider_hands_back_an_empty_set(ui, picker):
    provider = ui.make_manual_event_provider(
        show=lambda model: (model.pick_at(4.0), model.cancel()))

    provider(picker)

    assert picker.as_segment_walking_events() == ([], [], [], [])


def test_the_provider_is_accepted_by_collect_manual_events(gait_module, ui):
    """End to end across the seam: the UI's provider satisfies the pipeline's
    own validation, including the frame-count and trial-name checks."""
    class Analysis:
        markerDict = {"time": _times(40)}
        trial_name = "Trial3_1"
        eventDetectionSignals = {"r_calc": [0.0] * 40, "r_toe": [0.0] * 40,
                                 "l_calc": [0.0] * 40, "l_toe": [0.0] * 40}
        allow_manual_entry = True
        dflag = 0
        rhs = lhs = rto = lto = []

    def fake_window(model):
        for event_type, frame in (("rHS", 0.0), ("lTO", 3.0),
                                  ("lHS", 8.0), ("rTO", 12.0)):
            model.select(event_type)
            model.pick_at(frame)

    analysis = Analysis()
    analysis.manual_event_provider = ui.make_manual_event_provider(
        show=fake_window)

    rHS, lHS, rTO, lTO = gait_module.manual_steps(analysis)

    assert (rHS, lHS, rTO, lTO) == ([0], [8], [12], [3])


# -- what the operator reads ----------------------------------------------


def test_the_status_line_carries_the_pipelines_own_verdict(model):
    for event_type, frame in (("rHS", 0.0), ("lTO", 3.0), ("lHS", 8.0),
                              ("rTO", 12.0), ("rHS", 20.0)):
        model.select(event_type)
        model.pick_at(frame)

    line = model.status_line()

    assert "OK" in line
    assert "correct gait order" in line


def test_the_status_line_flags_an_out_of_order_set_without_refusing_it(model):
    """Reported, never enforced -- a pathological gait may genuinely violate
    the expected cycle."""
    model.pick_at(0.0)
    model.select("rTO")
    model.pick_at(3.0)

    assert "check" in model.status_line()
    assert model.picker.as_segment_walking_events()[0] == [0]


def test_the_status_line_tallies_every_event_type(model):
    model.pick_at(1.0)

    line = model.status_line()

    for event_type in ("rHS", "rTO", "lHS", "lTO"):
        assert event_type in line


def test_the_timeline_panel_lists_picks_in_time_order(model):
    model.select("lHS")
    model.pick_at(8.0)
    model.select("rHS")
    model.pick_at(2.0)

    lines = model.timeline_lines()

    assert "rHS" in lines[0]
    assert "lHS" in lines[1]


# -- drawing data ----------------------------------------------------------


def test_events_are_drawn_against_the_signal_the_detector_used(model):
    """Heel strikes on the calc trace, toe-offs on the toe trace -- matching
    what detect_gait_peaks ran find_peaks over."""
    model.select("rHS")
    model.pick_at(3.0)

    frames, values = model.events_for("rHS")

    assert frames == [3]
    assert values == [3.0]        # r_calc is i * 1.0


def test_toe_offs_are_drawn_against_the_toe_trace(model):
    model.select("rTO")
    model.pick_at(3.0)

    _frames, values = model.events_for("rTO")

    assert values == [6.0]        # r_toe is i * 2.0


def test_a_timeline_without_signals_still_yields_drawable_data(gait_module,
                                                              picker_module, ui):
    """A picker built outside segment_walking has no signals. The model must
    not crash on that -- the window reports it, the model degrades."""
    timeline = gait_module.MarkerTimeline(_times(10), name="bare")
    model = ui.EventPickerModel(picker_module.GaitEventPicker(timeline))
    model.pick_at(2.0)

    frames, values = model.events_for("rHS")

    assert frames == [2]
    assert values == [0.0]


# -- a window that never opened is not a decline ---------------------------


def test_a_window_that_never_opened_is_an_error_not_a_decline(ui, picker):
    """The dangerous ambiguity. segment_walking reads an empty picker as the
    operator declining and falls back to auto-trim -- but plt.show() returns
    immediately under a non-interactive backend, which also yields an empty
    picker. make_reports.py and make_comparison_figures.py force Agg
    process-wide at import, so any process touching either would silently lose
    the picker and the operator would never see a window."""
    provider = ui.make_manual_event_provider(show=lambda model: None)

    with pytest.raises(RuntimeError, match="never opened"):
        provider(picker)


def test_a_deliberate_cancel_is_not_an_error(ui, picker):
    """Cancel is how an operator declines on purpose; it must still reach
    segment_walking as an empty set rather than raising."""
    provider = ui.make_manual_event_provider(
        show=lambda model: model.cancel())

    assert provider(picker) is None
    assert picker.as_segment_walking_events() == ([], [], [], [])


def test_a_non_interactive_backend_is_refused_before_drawing(ui, model,
                                                             monkeypatch):
    matplotlib = pytest.importorskip("matplotlib")
    monkeypatch.setattr(matplotlib, "get_backend", lambda: "Agg")

    with pytest.raises(RuntimeError, match="never opens a window"):
        ui.show_picker_window(model)


# -- the panel clicked decides the leg -------------------------------------


def test_clicking_the_left_panel_records_a_left_event(ui, model):
    """An operator reading the left trace and clicking it while rHS is
    selected means a LEFT heel strike. Recording a right one there -- and
    drawing it on the other panel -- is a silent wrong answer of exactly the
    kind edit #13 was about."""
    model.select("rHS")

    assert model.event_type_for_panel("l") == "lHS"
    assert model.event_type_for_panel("r") == "rHS"


def test_the_event_kind_survives_the_leg_switch(ui, model):
    model.select("rTO")

    assert model.event_type_for_panel("l") == "lTO"


def test_picking_with_an_explicit_type_moves_the_selection(ui, model):
    """So the radio and the picker cannot disagree about what the next click
    will do."""
    model.select("rHS")
    model.pick_at(4.0, event_type="lHS")

    assert model.event_type == "lHS"
    assert model.picker.rows("lHS") == [4]
    assert model.picker.rows("rHS") == []


# -- the window itself -----------------------------------------------------
# The model tests above cannot see a typo in the plotting code, because none of
# it runs. These build the real figure under Agg with plt.show stubbed, which
# is the only part of the window that needs a display.


@pytest.fixture
def headless_pyplot(ui, monkeypatch):
    """Render the real window offscreen.

    The interactive-backend guard has to be neutralised to do this, which is
    the point of the guard: under Agg a real operator would get no window. It
    is stubbed here rather than given a production bypass, so nothing shipping
    can skip it by passing a flag.
    """
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    monkeypatch.setattr(ui, "assert_interactive_backend", lambda: None)
    shown = []
    real_show = plt.show
    plt.show = lambda *args, **kwargs: shown.append(True)
    try:
        yield plt, shown
    finally:
        plt.show = real_show
        plt.close("all")


def test_the_window_builds_and_blocks_on_show(ui, model, headless_pyplot):
    plt, shown = headless_pyplot

    window = ui.show_picker_window(model)

    assert len(window) == 4, "expected radio + done + cancel + clear"
    assert shown == [True], "the window must block until the operator closes it"


# -- the click wiring, driven for real -------------------------------------
# The model tests cover what a pick means. These cover the handler that turns
# a mouse event into one: the toolbar guard and the panel-to-leg mapping live
# only here, and neither is visible to the model.


class _MouseEvent:
    def __init__(self, inaxes, xdata, button=1):
        self.inaxes = inaxes
        self.xdata = xdata
        self.button = button


class _FakeToolbar:
    """Enough of matplotlib's navigation toolbar to set `mode`.

    `_wait_cursor_for_draw_cm` is not decoration: the Agg canvas calls it on
    every draw, so a toolbar stub without it turns a redraw into an
    AttributeError rather than exercising the guard."""

    def __init__(self, mode=""):
        self.mode = mode

    def _wait_cursor_for_draw_cm(self):
        import contextlib
        return contextlib.nullcontext()


@pytest.fixture
def live_window(ui, model, headless_pyplot):
    window = ui.show_picker_window(model)
    return window, model


def test_a_click_on_the_right_panel_marks_a_right_event(live_window):
    window, model = live_window
    model.select("rHS")

    window.on_click(_MouseEvent(window.axes[0], 12.0))

    assert model.picker.rows("rHS") == [12]


def test_a_click_on_the_left_panel_marks_a_left_event(live_window):
    """rHS is selected, but the operator clicked the LEFT trace. Recording a
    right heel strike there -- and drawing it on the other panel -- is a silent
    wrong answer of the same shape as edit #13."""
    window, model = live_window
    model.select("rHS")

    window.on_click(_MouseEvent(window.axes[1], 12.0))

    assert model.picker.rows("lHS") == [12]
    assert model.picker.rows("rHS") == []


def test_a_left_panel_click_keeps_the_event_kind(live_window):
    window, model = live_window
    model.select("rTO")

    window.on_click(_MouseEvent(window.axes[1], 20.0))

    assert model.picker.rows("lTO") == [20]


def test_a_zoom_drag_does_not_deposit_an_event(live_window):
    """matplotlib does not suppress user callbacks while the navigation
    toolbar is active, and zooming is the natural way to place an event
    precisely on a several-hundred-frame trial -- so without the guard every
    zoom rectangle marked a gait event at the drag origin."""
    window, model = live_window
    window.figure.canvas.toolbar = _FakeToolbar("zoom rect")

    window.on_click(_MouseEvent(window.axes[0], 12.0))

    assert model.picker.counts() == {"rHS": 0, "rTO": 0, "lHS": 0, "lTO": 0}


def test_a_pan_drag_does_not_deposit_an_event(live_window):
    window, model = live_window
    window.figure.canvas.toolbar = _FakeToolbar("pan/zoom")

    window.on_click(_MouseEvent(window.axes[0], 5.0))

    assert model.picker.rows("rHS") == []


def test_clicking_still_works_once_the_toolbar_is_idle(live_window):
    """The guard must not disable picking permanently -- an operator zooms in
    and then places the event."""
    window, model = live_window
    window.figure.canvas.toolbar = _FakeToolbar("zoom rect")
    window.on_click(_MouseEvent(window.axes[0], 12.0))

    window.figure.canvas.toolbar.mode = ""
    window.on_click(_MouseEvent(window.axes[0], 12.0))

    assert model.picker.rows("rHS") == [12]


def test_a_right_click_erases(live_window):
    window, model = live_window
    window.on_click(_MouseEvent(window.axes[0], 12.0))

    window.on_click(_MouseEvent(window.axes[0], 12.0, button=3))

    assert model.picker.rows("rHS") == []


def test_a_click_outside_any_panel_is_ignored(live_window):
    window, model = live_window

    window.on_click(_MouseEvent(None, 12.0))
    window.on_click(_MouseEvent(window.axes[0], None))

    assert model.picker.counts() == {"rHS": 0, "rTO": 0, "lHS": 0, "lTO": 0}


def test_the_window_shows_the_picked_events_list(ui, model, headless_pyplot):
    """Phase 2.2 asks for a table of picked events in time order. The model
    could produce one from the start; the window did not display it, so it was
    dead code everywhere but the tests."""
    model.select("rHS")
    model.pick_at(3.0)
    model.select("lTO")
    model.pick_at(9.0)

    ui.show_picker_window(model)

    text = ui._picked_panel_text(model)
    assert "picked events (2)" in text
    assert "rHS" in text and "lTO" in text
    assert "frame      3" in text


def test_the_picked_list_says_so_when_nothing_is_picked(ui, model):
    assert "none yet" in ui._picked_panel_text(model)


def test_the_picked_list_truncates_rather_than_overflowing(ui, model):
    """A long trial can carry more events than the column has room for."""
    for frame in range(0, 30):
        model.pick_at(float(frame))

    text = ui._picked_panel_text(model, max_rows=5)

    assert "picked events (30)" in text
    assert "... 25 earlier" in text
    assert len(text.splitlines()) == 7      # heading + notice + 5 rows


def test_the_status_line_is_wrapped_not_clipped(ui, model, headless_pyplot):
    """An out-of-order verdict is a full sentence naming two events and what
    was expected between them. On one line it ran off the right edge of the
    figure and the operator lost the half saying what to do about it."""
    model.pick_at(0.0)
    model.select("rTO")
    model.pick_at(3.0)

    window = ui.show_picker_window(model)

    status = [artist for artist in window.figure.texts
              if "check" in artist.get_text()]
    assert status, "no status text found on the figure"
    assert "\n" in status[0].get_text(), "the verdict was not wrapped"


def test_the_window_refuses_a_trial_with_nothing_to_plot(gait_module, ui,
                                                         picker_module,
                                                         headless_pyplot):
    """Reported, not drawn blank: an operator staring at empty axes has no way
    to tell that the signals were missing rather than flat."""
    timeline = gait_module.MarkerTimeline(_times(10), name="bare")
    model = ui.EventPickerModel(picker_module.GaitEventPicker(timeline))

    with pytest.raises(ValueError, match="no detection signals"):
        ui.show_picker_window(model)
