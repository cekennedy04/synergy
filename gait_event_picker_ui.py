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
"""
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
        self.picker.mark(event_type or self.event_type, frame)
        return frame

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
    """
    def provider(picker):
        model = model_factory(picker)
        (show or show_picker_window)(model)
        return None
    return provider


def show_picker_window(model):  # pragma: no cover - needs a display
    """The matplotlib window. Thin on purpose: every decision is in the model.

    Blocks until the operator closes it, which is what `segment_walking`
    wants -- it calls this synchronously and reads the picker straight after.
    """
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Button, RadioButtons

    motion = model.picker.motion
    if not motion.signals:
        raise ValueError(
            "this trial carries no detection signals to plot, so there is "
            "nothing for an operator to pick against. segment_walking stashes "
            "them as eventDetectionSignals; a picker built outside it must "
            "supply them on the timeline.")

    frames = range(motion.n_rows)
    figure, axes = plt.subplots(
        len(LEG_PANELS), 1, sharex=True, figsize=(13, 7.5))
    figure.canvas.manager.set_window_title(
        f"Pick gait events - {motion.name or 'trial'}")
    figure.subplots_adjust(left=0.22, right=0.98, top=0.92, bottom=0.10)

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
        axis.legend(loc='upper right', fontsize=8)
        axis.grid(alpha=0.25)
    axes[-1].set_xlabel('frame index (not time)')

    status = figure.text(0.22, 0.965, '', fontsize=9, family='monospace')
    readout = figure.text(0.78, 0.02, '', fontsize=9, family='monospace')

    def redraw():
        for event_type, artist in marker_artists.items():
            picked, values = model.events_for(event_type)
            artist.set_data(picked, values)
        status.set_text(model.status_line())
        figure.canvas.draw_idle()

    radio = RadioButtons(figure.add_axes([0.02, 0.62, 0.16, 0.25]),
                         EVENT_TYPES)

    def on_select(label):
        model.select(label)
        redraw()
    radio.on_clicked(on_select)

    def on_click(event):
        if event.inaxes not in list(axes) or event.xdata is None:
            return
        # Right-click erases, matching the "delete" the plan asks for without
        # a separate mode the operator has to remember to leave.
        if event.button == 3:
            model.erase_at(event.xdata)
        else:
            model.pick_at(event.xdata)
        redraw()
    figure.canvas.mpl_connect('button_press_event', on_click)

    def on_move(event):
        if event.inaxes in list(axes) and event.xdata is not None:
            readout.set_text(model.readout(event.xdata))
            figure.canvas.draw_idle()
    figure.canvas.mpl_connect('motion_notify_event', on_move)

    done = Button(figure.add_axes([0.02, 0.50, 0.16, 0.06]), 'Use these events')
    done.on_clicked(lambda _event: plt.close(figure))

    def on_cancel(_event):
        # Empties the picker: segment_walking reads an empty set as a decline
        # and falls back to the auto-trim rung rather than failing the trial.
        model.cancel()
        plt.close(figure)
    cancel = Button(figure.add_axes([0.02, 0.42, 0.16, 0.06]),
                    'Cancel (use auto-trim)')
    cancel.on_clicked(on_cancel)

    clear = Button(figure.add_axes([0.02, 0.34, 0.16, 0.06]), 'Clear all')
    clear.on_clicked(lambda _event: (model.clear(), redraw()))

    redraw()
    plt.show()
    # Keep the widgets referenced until the window is gone; matplotlib drops
    # callbacks on garbage-collected widget objects.
    return radio, done, cancel, clear
