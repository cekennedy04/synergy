"""Pick gait events by clicking on the curves the detector already failed on.

Built 2026-09-01. Phase 2.2's UI, on top of `gait_event_picker.GaitEventPicker`
(the data layer) and wired into `segment_walking` through
`gait_analysis_UCM_fixed`'s `manual_event_provider` seam.

**Why matplotlib and not the 3D visualizer.** Phase 2.1 measured it: a Tk
mainloop and the Simbody visualizer in one process deadlock -- the identical
frame sequence renders in 1.4s from a plain loop and hangs indefinitely under
`root.after()`/`mainloop()`, because Simbody blocks on a pipe Tk's loop does
not yield for. `motion_scrubber.ModelView` says so in its own docstring. The
plan named the fallback for exactly this case: a 2D picker over the joint
signals, no 3D view, far less risk, and sufficient for picking heel strikes.
matplotlib's own Tk backend is fine here because Simbody is not in the process.

**What the operator sees is what the detector saw.** The curves plotted are
`r_calc_rel_x`, `r_toe_rel_x`, `l_calc_rel_x`, `l_toe_rel_x` -- the same four
`detect_gait_peaks` runs `find_peaks` over, carried here on the timeline's
`signals`. Picking against a different rendering of the trial would mean the
human and the automatic rung are answering different questions.

**The x axis is the frame index.** Not time. A click maps to a frame by
rounding, with no time conversion anywhere on the path: the picker stores
frames, `segment_walking` consumes frames, so introducing seconds in between
would add a conversion that can only lose. Time is shown in the readout for
orientation and is never an input.

Note this is NOT justified by irregular sampling, which earlier drafts of this
docstring and of `gait_event_picker.py`'s claimed. Measured 2026-09-01: all 77
.trc files in Data/ have a single distinct dt of 0.016667, as do the .mot
files. The frames-only path is right because it removes a conversion, not
because the conversion would be wrong here.

**Ordering is reported, never enforced.** The verdict line runs the picker's
own `ordering_report`, which mirrors `detect_correct_order`, so the operator
sees the pipeline's judgment while picking instead of a rejection afterwards.
Saving an out-of-order set is allowed: a pathological gait may genuinely
violate the expected cycle, and this project stopped hard-refusing trials on
2026-08-27.

**The model is separable from the window.** `EventPickerModel` holds every
decision -- which frame a click means, what the summary says, what the verdict
is -- and touches no matplotlib. That is the only reason any of this is
testable on a machine with no display, which is also every machine that runs
the test suite here.

**Who opens this window, and who deliberately does not.** Wired 2026-09-03;
before that nothing passed `manual_event_provider` and the window never opened
in production, however complete it was. What each caller does now:

  Examples/gaitAnalysis-UCM.py  run_interactive   -- opens this window
  Examples/gaitAnalysis-UCM.py  run_batch         -- allow_manual_entry=False
  clinician_gui.py:449,454                        -- allow_manual_entry=False
  rerun_survey.py:112                             -- allow_manual_entry=False

`run_interactive` is the right and only place. It was already interactive and
already stopped to ask: a trial auto-trim could not segment fell through to a
stdin prompt for four lists of raw frame indices, typed against no picture of
the trial. The window replaces that prompt rather than adding an interruption.
Everything unattended keeps `allow_manual_entry=False`, so no batch run can
acquire a window by any route.

Wire another caller with one keyword at the construction site:

    from gait_event_picker_ui import (make_manual_event_provider,
                                      reuse_across_legs)
    provider = reuse_across_legs(make_manual_event_provider())
    gait_analysis(..., allow_manual_entry=True,
                  manual_event_provider=provider)

`reuse_across_legs` is not optional wherever a trial is analysed twice. Each
`gait_analysis` construction runs `segment_walking`, so the two legs of one
trial would otherwise open two windows asking one operator the same question
about the same curves -- and could come back with two different answers.

Still deliberately not wired: clinician_gui.py. Whether a clinician-facing
GUI should stop and ask for hand-picked events -- rather than reporting the
trial as unsegmentable -- is a product decision, not a wiring one, and that
GUI runs trials in a batch loop on a worker thread, where blocking on a window
per failed trial is exactly what allow_manual_entry=False exists to prevent.
"""
import textwrap

from gait_event_picker import EVENT_TYPES, GaitEventPicker

# Drawn per leg: which signals belong to which axis, and which event types are
# picked on it. Keyed to the names gait_analysis_UCM_fixed stashes.
LEG_PANELS = (
    {'leg': 'r', 'title': 'Right leg',
     'signals': ('r_calc', 'r_toe'), 'events': ('rHS', 'rTO')},
    {'leg': 'l', 'title': 'Left leg',
     'signals': ('l_calc', 'l_toe'), 'events': ('lHS', 'lTO')},
)

# Heel strikes and toe-offs want telling apart at a glance, and left from
# right. Deliberately not the default matplotlib cycle, which would give two
# events the same colour across panels.
EVENT_STYLE = {
    'rHS': {'color': '#c1121f', 'marker': 'v', 'label': 'right heel strike'},
    'rTO': {'color': '#f08c00', 'marker': '^', 'label': 'right toe off'},
    'lHS': {'color': '#0353a4', 'marker': 'v', 'label': 'left heel strike'},
    'lTO': {'color': '#2a9d8f', 'marker': '^', 'label': 'left toe off'},
}

SIGNAL_LABEL = {
    'r_calc': 'right heel (calc)', 'r_toe': 'right toe',
    'l_calc': 'left heel (calc)', 'l_toe': 'left toe',
}


class EventPickerModel:
    """Every decision the picker window makes, with no window attached.

    Wraps a GaitEventPicker rather than replacing it: the picker owns storage,
    validation and the return contract; this owns what the operator is
    currently doing.
    """

    def __init__(self, picker, event_type='rHS'):
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"unknown event type {event_type!r}; expected one of "
                f"{list(EVENT_TYPES)}.")
        self.picker = picker
        self.event_type = event_type
        self.cancelled = False

    # -- what the operator is doing ---------------------------------------

    def select(self, event_type):
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"unknown event type {event_type!r}; expected one of "
                f"{list(EVENT_TYPES)}.")
        self.event_type = event_type
        return self.event_type

    def frame_for(self, x):
        """The frame a click at plot coordinate `x` means.

        Rounded, then clamped: clicking just past either end of the axes is an
        operator aiming at the first or last frame, not an error worth
        refusing. No time conversion anywhere -- the axis IS the frame index.
        """
        frame = int(round(x))
        return max(0, min(self.picker.motion.n_rows - 1, frame))

    def pick_at(self, x, event_type=None):
        """Mark the selected event at the frame under a click."""
        frame = self.frame_for(x)
        chosen = event_type or self.event_type
        self.picker.mark(chosen, frame)
        # The selection follows the pick, so the radio and the picker never
        # disagree about what the next click will do.
        self.event_type = chosen
        return frame

    def event_type_for_panel(self, leg):
        """The selected event kind, moved to the leg whose panel was clicked.

        Clicking the left trace while 'rHS' is selected means a LEFT heel
        strike -- the operator is pointing at a left-leg event. The KIND of
        event (heel strike vs toe off) is what the radio chooses; the panel
        chooses the leg.
        """
        kind = self.event_type[1:]                 # 'HS' or 'TO'
        return ('r' if leg == 'r' else 'l') + kind

    def erase_at(self, x, tolerance=5):
        """Remove the nearest picked event of any type within `tolerance`
        frames of a click, and say what was removed.

        Any type, not just the selected one: an operator who spots a stray
        marker wants it gone without first having to work out which button
        made it.
        """
        frame = self.frame_for(x)
        candidates = [(abs(row - frame), row, name)
                      for row, _time, name in self.picker.timeline()]
        if not candidates:
            return None
        distance, row, name = min(candidates)
        if distance > tolerance:
            return None
        self.picker.unmark(name, row)
        return row, name

    def clear(self, event_type=None):
        self.picker.clear(event_type)

    def cancel(self):
        """Decline to pick. segment_walking reads an empty set as a decline and
        falls back to the auto-trim rung, so this must actually empty the
        picker rather than merely close the window."""
        self.picker.clear()
        self.cancelled = True

    # -- what the operator reads ------------------------------------------

    def verdict(self):
        """(ok, message) from the picker's own ordering report."""
        return self.picker.ordering_report()

    def status_line(self):
        counts = self.picker.counts()
        tally = '  '.join(f'{name} {counts[name]}' for name in EVENT_TYPES)
        ok, message = self.verdict()
        return f"picking {self.event_type}   |   {tally}   |   " \
               f"{'OK' if ok else 'check'}: {message}"

    def readout(self, x):
        """The frame and time under the cursor, for the corner of the window."""
        frame = self.frame_for(x)
        return f"frame {frame}   t = {self.picker.motion.time_at(frame):.3f}s"

    def timeline_lines(self):
        """The picked set in time order, one line each, for a side panel."""
        return [f"{name}  frame {row:>6}   t = {time:.3f}s"
                for row, time, name in self.picker.timeline()]

    def events_for(self, event_type):
        """(frames, values) for drawing this event type on its signal."""
        frames = self.picker.rows(event_type)
        signal = self._signal_for(event_type)
        if signal is None:
            return frames, [0.0] * len(frames)
        return frames, [signal[frame] for frame in frames]

    def _signal_for(self, event_type):
        """The curve an event type is drawn against: heel strikes on the calc
        trace, toe-offs on the toe trace, matching what the detector used."""
        name = ('r_calc' if event_type == 'rHS' else
                'r_toe' if event_type == 'rTO' else
                'l_calc' if event_type == 'lHS' else 'l_toe')
        return self.picker.motion.signals.get(name)


def make_manual_event_provider(show=None, model_factory=EventPickerModel):
    """A `manual_event_provider` for gait_analysis: opens the picker window.

    Returns None, having marked events on the picker it was handed -- the
    contract `collect_manual_events` expects. `show` is injected so the tests
    can drive the whole provider path without a display; it defaults to the
    real matplotlib window.

    **An empty picker is ambiguous, and the ambiguity is dangerous.**
    `segment_walking` reads an empty set as the operator declining, and falls
    back to auto-trim. But a window that never opened also returns an empty
    set -- `plt.show()` returns immediately under a non-interactive backend --
    and this repo forces `matplotlib.use("Agg")` process-wide at import in
    make_reports.py and make_comparison_figures.py. Any process that has
    touched either would lose the picker entirely and silently drop to
    auto-trim, with the operator never seeing a window and never being told.
    `EventPickerModel.cancelled` is what tells the two apart, so it is checked
    here rather than left for nobody to read.
    """
    def provider(picker):
        model = model_factory(picker)
        (show or show_picker_window)(model)
        if not any(picker.counts().values()) and not model.cancelled:
            raise RuntimeError(
                "the gait-event picker closed without any events being picked "
                "and without Cancel being pressed, which usually means the "
                "window never opened. matplotlib's backend is "
                + _backend_name() + "; an interactive backend is required. "
                "make_reports.py and make_comparison_figures.py force Agg "
                "process-wide at import, so importing either before picking "
                "disables the picker. Press Cancel to decline a trial "
                "deliberately -- that falls back to auto-trim.")
        return None
    return provider


def reuse_across_legs(provider):
    """Wrap a provider so one trial asks the operator exactly once.

    `run_gait_analysis` builds `gait_analysis` twice per trial -- `leg='r'`
    then `leg='l'`, because the symmetry metric is only defined by comparing
    both -- and each constructor runs `segment_walking` over the same trial.
    So a trial auto-trim cannot segment fails for both legs, and an unwrapped
    provider opens the picker window twice for one trial: the same operator,
    the same curves, the same question. The second answer can also differ from
    the first, which would put the two legs of one trial on different events.

    The remembered answer includes a decline. Cancel means "use auto-trim",
    and re-opening on the other leg the window the operator just dismissed is
    the same failure in the other direction.

    **Nothing is remembered for an unnamed trial.** Frame count is not
    identity -- fixed-duration walk captures from one participant routinely
    share one -- so with no name to tell two trials apart the safe answer is
    to ask again. `collect_manual_events` refuses a cross-trial replay for
    exactly this reason; this declines to manufacture one.
    """
    remembered = {}

    def wrapper(picker):
        motion = picker.motion
        name = getattr(motion, 'name', '') or ''
        # n_rows is in the key as well as the name: trimming changes the frame
        # count, and rows from one index space do not mean anything in
        # another. A name match with a length mismatch is a different trial
        # state, not the same trial.
        key = (name, motion.n_rows) if name else None

        if key is not None and key in remembered:
            for event_type, rows in remembered[key].items():
                for row in rows:
                    picker.mark(event_type, row)
            # None, not the remembered picker: the contract is to mark the
            # picker `collect_manual_events` built over THIS analysis, which
            # is the one whose frame space and trial name it will check.
            return None

        returned = provider(picker)
        source = picker if returned is None else returned
        # Read through as_segment_walking_events, which is the only shape
        # collect_manual_events actually requires of a returned picker. A
        # provider handing back something else is a wiring mistake, and
        # collect_manual_events has the diagnostic for it -- so pass it along
        # unremembered rather than dying here on a missing attribute and
        # burying that message.
        if key is not None and hasattr(source, 'as_segment_walking_events'):
            rHS, lHS, rTO, lTO = source.as_segment_walking_events()
            remembered[key] = {'rHS': list(rHS), 'lHS': list(lHS),
                               'rTO': list(rTO), 'lTO': list(lTO)}
        return returned

    return wrapper


def _picked_panel_text(model, max_rows=18):
    """The picked set for the side panel, newest kept when it overflows.

    Carries the frame AND the time for every pick, which is also how an
    operator reconciles the ordering verdict with the plot: the verdict names
    events in seconds (it comes from the shared picker, which reports that
    way) while the axis is in frames, and this list is where the two meet.
    """
    lines = model.timeline_lines()
    if not lines:
        return 'picked events\n(none yet)'
    heading = 'picked events (%d)' % len(lines)
    if len(lines) > max_rows:
        return '\n'.join([heading, '... %d earlier' % (len(lines) - max_rows)]
                         + lines[-max_rows:])
    return '\n'.join([heading] + lines)


def _backend_name():
    try:
        import matplotlib
        return repr(matplotlib.get_backend())
    except Exception:                                  # pragma: no cover
        return 'unavailable'


# Backends that draw nothing and return from plt.show() immediately. Picking
# against one is not possible, and failing loudly beats an empty set that
# segment_walking would read as a considered decline.
NON_INTERACTIVE_BACKENDS = ('agg', 'pdf', 'ps', 'svg', 'cairo', 'template')


def assert_interactive_backend():
    """Refuse to 'show' a window that cannot be shown."""
    import matplotlib
    backend = matplotlib.get_backend()
    if backend.lower().replace('module://', '') in NON_INTERACTIVE_BACKENDS:
        raise RuntimeError(
            "matplotlib's backend is " + repr(backend) + ", which renders to a "
            "file and never opens a window, so there is nothing for an "
            "operator to pick on. Run the picker in a process that has not "
            "forced a non-interactive backend -- make_reports.py and "
            "make_comparison_figures.py both call matplotlib.use('Agg') at "
            "import time.")


def build_picker_view(model, figure):
    """Draw the whole picker onto `figure` and wire it up. Returns a
    PickerWindow holding every part a caller (or a test) needs to reach.

    Split out of `show_picker_window` on 2026-09-03 so the standalone pyplot
    window and the Tk-embedded one in `gait_event_picker_tk` are the same
    picker rather than two that drift apart. Everything here is
    backend-agnostic: it touches `figure` and matplotlib's own widgets, never
    pyplot and never tkinter, so it draws on whichever canvas the caller has
    already attached. Showing and blocking is the only part the two callers
    genuinely differ on, and that is what each keeps for itself.

    `figure.canvas` must already exist -- the click and motion handlers are
    connected here.
    """
    from matplotlib.widgets import Button, RadioButtons

    motion = model.picker.motion
    if not motion.signals:
        raise ValueError(
            "this trial carries no detection signals to plot, so there is "
            "nothing for an operator to pick against. segment_walking stashes "
            "them as eventDetectionSignals; a picker built outside it must "
            "supply them on the timeline.")

    frames = range(motion.n_rows)
    axes = figure.subplots(len(LEG_PANELS), 1, sharex=True)
    # top leaves room for a three-line wrapped verdict above the first panel's
    # title. At 0.92 a two-line verdict sat on top of "Right leg".
    figure.subplots_adjust(left=0.22, right=0.98, top=0.88, bottom=0.10)

    marker_artists = {}
    for axis, panel in zip(axes, LEG_PANELS):
        for name in panel['signals']:
            values = motion.signals.get(name)
            if values is not None:
                axis.plot(frames, values, linewidth=1.0,
                          label=SIGNAL_LABEL.get(name, name))
        for event_type in panel['events']:
            style = EVENT_STYLE[event_type]
            marker_artists[event_type] = axis.plot(
                [], [], style['marker'], color=style['color'], markersize=9,
                linestyle='none', label=style['label'])[0]
        axis.set_title(panel['title'], loc='left', fontsize=10)
        # 'best', not 'upper right': the walking is at whichever end of the
        # trial the subject started moving, and a fixed corner put the legend
        # squarely on top of the peaks an operator is trying to click.
        axis.legend(loc='best', fontsize=8, framealpha=0.85)
        axis.grid(alpha=0.25)
    axes[-1].set_xlabel('frame index (not time)')

    status = figure.text(0.22, 0.975, '', fontsize=9, family='monospace',
                         va='top')
    readout = figure.text(0.78, 0.02, '', fontsize=9, family='monospace')
    # The picked set, in time order, in the empty column under the buttons.
    # Phase 2.2 asks for this explicitly, and without it the only record of
    # what has been picked is the markers themselves -- which is no help when
    # two land within a few frames of each other.
    picked_list = figure.text(0.02, 0.30, '', fontsize=8, family='monospace',
                              va='top')

    def redraw():
        for event_type, artist in marker_artists.items():
            picked, values = model.events_for(event_type)
            artist.set_data(picked, values)
        # Wrapped, because the ordering verdict is a full sentence naming two
        # events and what was expected between them -- on one line it ran off
        # the right edge of the figure and the operator lost the half that
        # says what to do about it.
        status.set_text('\n'.join(textwrap.wrap(model.status_line(), 118)))
        picked_list.set_text(_picked_panel_text(model))
        figure.canvas.draw_idle()

    radio = RadioButtons(figure.add_axes([0.02, 0.62, 0.16, 0.25]),
                         EVENT_TYPES)

    def on_select(label):
        model.select(label)
        redraw()
    radio.on_clicked(on_select)

    panel_for_axis = {id(axis): panel for axis, panel in zip(axes, LEG_PANELS)}

    def on_click(event):
        if event.inaxes not in list(axes) or event.xdata is None:
            return
        # Zoom-rect and pan do NOT suppress user callbacks in matplotlib, and
        # zooming is the natural way to place an event precisely on a
        # several-hundred-frame trial -- so without this every zoom rectangle
        # and every pan drag would deposit a spurious gait event at the drag
        # origin.
        toolbar = getattr(figure.canvas, 'toolbar', None)
        if getattr(toolbar, 'mode', ''):
            return
        # Right-click erases, matching the "delete" the plan asks for without
        # a separate mode the operator has to remember to leave.
        if event.button == 3:
            model.erase_at(event.xdata)
        else:
            # The panel clicked decides the leg. An operator reading the left
            # trace and clicking on it while rHS is still selected means a LEFT
            # heel strike; recording a right one there, and drawing it on the
            # other panel, is a silent wrong answer of exactly the kind edit
            # #13 was about.
            panel = panel_for_axis[id(event.inaxes)]
            model.pick_at(event.xdata,
                          event_type=model.event_type_for_panel(panel['leg']))
        redraw()
        radio.set_active(list(EVENT_TYPES).index(model.event_type))
    figure.canvas.mpl_connect('button_press_event', on_click)

    def on_move(event):
        if event.inaxes in list(axes) and event.xdata is not None:
            readout.set_text(model.readout(event.xdata))
            figure.canvas.draw_idle()
    figure.canvas.mpl_connect('motion_notify_event', on_move)

    # The widgets are carried on the returned object rather than dropped:
    # matplotlib discards callbacks belonging to garbage-collected widgets, and
    # the handlers are returned so the click wiring -- the toolbar guard and
    # the panel-to-leg mapping, neither of which the model can see -- is
    # reachable by a test instead of being untestable closure.
    window = PickerWindow(figure=figure, axes=list(axes),
                          widgets=(radio,), on_click=on_click,
                          on_move=on_move, redraw=redraw)

    done = Button(figure.add_axes([0.02, 0.50, 0.16, 0.06]), 'Use these events')
    done.on_clicked(lambda _event: window.close())

    def on_cancel(_event):
        # Empties the picker: segment_walking reads an empty set as a decline
        # and falls back to the auto-trim rung rather than failing the trial.
        model.cancel()
        window.close()
    cancel = Button(figure.add_axes([0.02, 0.42, 0.16, 0.06]),
                    'Cancel (use auto-trim)')
    cancel.on_clicked(on_cancel)

    clear = Button(figure.add_axes([0.02, 0.34, 0.16, 0.06]), 'Clear all')
    clear.on_clicked(lambda _event: (model.clear(), redraw()))

    window.buttons = (done, cancel, clear)
    redraw()
    return window


def show_picker_window(model):  # pragma: no cover - needs a display
    """The standalone matplotlib window, for a process with no Tk app of its
    own: `Examples/gaitAnalysis-UCM.py`'s interactive run, and
    `rescue_trial.py`.

    Blocks until the operator closes it, which is what `segment_walking`
    wants -- it calls this synchronously and reads the picker straight after.

    Inside the clinician GUI use `gait_event_picker_tk.show_picker_in_tk`
    instead. `plt.show()` starts a second Tk mainloop next to the one the GUI
    is already running, and the GUI would be calling this from its pipeline
    worker thread, where a matplotlib window deadlocks outright (measured
    2026-09-03).
    """
    import matplotlib.pyplot as plt

    assert_interactive_backend()
    figure = plt.figure(figsize=(13, 7.5))
    figure.canvas.manager.set_window_title(
        "Pick gait events - %s" % (model.picker.motion.name or 'trial'))
    window = build_picker_view(model, figure)
    window.close = lambda: plt.close(figure)
    plt.show()
    return window


class PickerWindow:
    """The live window's parts, kept addressable after it is built."""

    def __init__(self, figure, axes, widgets, on_click, on_move, redraw):
        self.figure = figure
        self.axes = axes
        self.widgets = widgets
        self.on_click = on_click
        self.on_move = on_move
        self.redraw = redraw
        self.buttons = ()
        # Replaced by whoever shows the window -- plt.close for the standalone
        # figure, destroy() for an embedded Tk toplevel. The default keeps
        # "Use these events" a no-op rather than an AttributeError if a new
        # caller forgets to set it.
        self.close = lambda: None

    def __len__(self):
        return len(self.widgets) + len(self.buttons)
